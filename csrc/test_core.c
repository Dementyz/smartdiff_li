/* Тесты ядра на чистом C: make test-c (или make test-c-asan). */
#include <stdio.h>
#include <string.h>

#include "sd_core.h"

static int failures = 0;

#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
            failures++;                                                 \
        }                                                               \
    } while (0)

static void test_graph_edges(void) {
    sd_graph g;
    sd_graph_init(&g);
    CHECK(sd_graph_add_nodes(&g, 3) == 0);
    CHECK(sd_graph_add_nodes(&g, 2) == 3);
    CHECK(sd_graph_add_edge(&g, 0, 1, 0, 10) == SD_OK);
    CHECK(sd_graph_add_edge(&g, 0, 1, 1, 11) == SD_OK); /* дубликат становится точным */
    CHECK(sd_graph_add_edge(&g, 0, 1, 0, 12) == SD_OK); /* и не теряет точность */
    CHECK(sd_graph_add_edge(&g, 0, 0, 1, 1) == SD_OK);  /* петля игнорируется */
    CHECK(sd_graph_add_edge(&g, 0, 9, 1, 1) == SD_EBADID);
    CHECK(sd_graph_add_edge(&g, -1, 0, 1, 1) == SD_EBADID);
    CHECK(g.edges == 1);
    CHECK(g.adj[0].len == 1 && g.adj[0].items[0].certain == 1 && g.adj[0].items[0].line == 11);
    sd_graph_free(&g);
}

static void test_trace(void) {
    /* 0 <- 1 <- 2 <- 3, и 0 <- 4 (вероятно), 4 <- 3 */
    sd_graph g;
    sd_graph_init(&g);
    sd_graph_add_nodes(&g, 5);
    sd_graph_add_edge(&g, 0, 1, 1, 1);
    sd_graph_add_edge(&g, 1, 2, 1, 2);
    sd_graph_add_edge(&g, 2, 3, 1, 3);
    sd_graph_add_edge(&g, 0, 4, 0, 4);
    sd_graph_add_edge(&g, 4, 3, 1, 5);

    sd_hits hits = {0};
    int32_t origin = 0;
    CHECK(sd_graph_trace(&g, &origin, 1, NULL, 0, -1, &hits) == SD_OK);
    CHECK(hits.len == 4);
    CHECK(hits.items[0].node == 1 && hits.items[0].depth == 1 && hits.items[0].certain);
    CHECK(hits.items[1].node == 4 && hits.items[1].depth == 1 && !hits.items[1].certain);
    CHECK(hits.items[2].node == 2 && hits.items[2].depth == 2 && hits.items[2].certain);
    /* 3 найден через 4 раньше, чем через 2: точность наследуется от вероятного пути */
    CHECK(hits.items[3].node == 3 && hits.items[3].depth == 2 && !hits.items[3].certain);

    CHECK(sd_graph_trace(&g, &origin, 1, NULL, 0, 1, &hits) == SD_OK);
    CHECK(hits.len == 2);
    CHECK(sd_graph_trace(&g, &origin, 1, NULL, 0, 0, &hits) == SD_OK);
    CHECK(hits.len == 0);

    sd_hit seeds[] = {{2, 0, 42, 1}, {2, 0, 43, 0}};
    CHECK(sd_graph_trace(&g, &origin, 1, seeds, 2, -1, &hits) == SD_OK);
    CHECK(hits.len == 2);
    CHECK(hits.items[0].node == 2 && hits.items[0].line == 42 && hits.items[0].depth == 1);
    CHECK(hits.items[1].node == 3 && hits.items[1].depth == 2);

    int32_t bad = 7;
    CHECK(sd_graph_trace(&g, &bad, 1, NULL, 0, -1, &hits) == SD_EBADID);
    sd_hits_free(&hits);
    sd_graph_free(&g);
}

static void test_trace_large_chain(void) {
    /* длинная цепочка заставляет буфер результатов многократно расти */
    enum { N = 20000 };
    sd_graph g;
    sd_graph_init(&g);
    sd_graph_add_nodes(&g, N);
    for (int32_t i = 1; i < N; i++)
        CHECK(sd_graph_add_edge(&g, i - 1, i, 1, i) == SD_OK);
    sd_hits hits = {0};
    int32_t origin = 0;
    CHECK(sd_graph_trace(&g, &origin, 1, NULL, 0, -1, &hits) == SD_OK);
    CHECK(hits.len == N - 1 && hits.items[N - 2].depth == N - 1);
    sd_hits_free(&hits);
    sd_graph_free(&g);
}

#define P(name, kind, def) {name, kind, def}

static void test_signature(void) {
    sd_param a[] = {P("a", SD_POSITIONAL, 0)};
    sd_param ab[] = {P("a", SD_POSITIONAL, 0), P("b", SD_POSITIONAL, 0)};
    sd_param ab_opt[] = {P("a", SD_POSITIONAL, 0), P("b", SD_POSITIONAL, 1)};
    sd_param ba[] = {P("b", SD_POSITIONAL, 0), P("a", SD_POSITIONAL, 0)};
    sd_param acb[] = {P("a", SD_POSITIONAL, 0), P("c", SD_POSITIONAL, 1), P("b", SD_POSITIONAL, 0)};
    sd_param a_var[] = {P("a", SD_POSITIONAL, 0), P("args", SD_VARARG, 0), P("kw", SD_KWARG, 0)};
    sd_param a_kw[] = {P("a", SD_KWONLY, 0)};
    sd_param a_def[] = {P("a", SD_POSITIONAL, 1)};

    CHECK(sd_signature_break(a, 1, ab, 2));        /* новый обязательный */
    CHECK(!sd_signature_break(a, 1, ab_opt, 2));   /* новый необязательный */
    CHECK(sd_signature_break(ab, 2, a, 1));        /* удалён */
    CHECK(sd_signature_break(ab, 2, ba, 2));       /* переставлены */
    CHECK(sd_signature_break(ab, 2, acb, 3));      /* вставка в середину */
    CHECK(!sd_signature_break(a, 1, a_var, 3));    /* *args и **kw */
    CHECK(sd_signature_break(a, 1, a_kw, 1));      /* сменил вид */
    CHECK(sd_signature_break(a_def, 1, a, 1));     /* пропало значение по умолчанию */
    CHECK(!sd_signature_break(a, 1, a_def, 1));
    CHECK(!sd_signature_break(NULL, 0, NULL, 0));
}

static void test_risk(void) {
    sd_change_info body = {SD_BODY, 0, 1, 0, 1, 2, 0};
    CHECK(sd_change_score(&body) == 3.0 * 1.0 * (1 + 0.3 * 1 + 0.05 * 1));
    sd_change_info removed = {SD_REMOVED, 0, 1, 0, 2, 2, 5};
    CHECK(sd_change_score(&removed) == 6.0 * (1 + 0.3 * 2) + 15.0 * 3);
    sd_change_info private_sig = {SD_SIGNATURE, 1, 0, 0, 0, 0, 0};
    CHECK(sd_change_score(&private_sig) == 4.0);
    sd_change_info test_file = {SD_SIGNATURE, 0, 1, 1, 0, 0, 0};
    CHECK(sd_change_score(&test_file) == 2.0 * 0.2);
    sd_change_info doc = {SD_DOC, 0, 1, 0, 50, 100, 0};
    CHECK(sd_change_score(&doc) == 0.0);

    CHECK(strcmp(sd_level_for(0), "low") == 0);
    CHECK(strcmp(sd_level_for(9.99), "low") == 0);
    CHECK(strcmp(sd_level_for(10), "medium") == 0);
    CHECK(strcmp(sd_level_for(25), "high") == 0);
    CHECK(strcmp(sd_level_for(45), "critical") == 0);
}

int main(void) {
    test_graph_edges();
    test_trace();
    test_trace_large_chain();
    test_signature();
    test_risk();
    if (failures) {
        fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    puts("all C core tests passed");
    return 0;
}
