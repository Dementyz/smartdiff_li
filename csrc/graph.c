#include <stdlib.h>
#include <string.h>

#include "sd_core.h"

/* Новый буфер нужного размера или NULL; при ошибке старый буфер не трогается. */
static void *grow(void *items, int32_t *cap, int32_t need, size_t size) {
    int32_t ncap = *cap ? *cap : 4;
    while (ncap < need) {
        if (ncap > INT32_MAX / 2)
            return NULL;
        ncap *= 2;
    }
    void *p = realloc(items, (size_t)ncap * size);
    if (p)
        *cap = ncap;
    return p;
}

void sd_graph_init(sd_graph *g) { memset(g, 0, sizeof *g); }

void sd_graph_free(sd_graph *g) {
    for (int32_t i = 0; i < g->n; i++)
        free(g->adj[i].items);
    free(g->adj);
    sd_graph_init(g);
}

int32_t sd_graph_add_nodes(sd_graph *g, int32_t count) {
    if (count < 0 || g->n > INT32_MAX - count)
        return SD_ENOMEM;
    int32_t need = g->n + count;
    if (need > g->cap) {
        sd_edges *p = grow(g->adj, &g->cap, need, sizeof *g->adj);
        if (!p)
            return SD_ENOMEM;
        g->adj = p;
    }
    memset(g->adj + g->n, 0, (size_t)count * sizeof *g->adj);
    int32_t first = g->n;
    g->n = need;
    return first;
}

int sd_graph_add_edge(sd_graph *g, int32_t used, int32_t user, int certain, int32_t line) {
    if (used < 0 || used >= g->n || user < 0 || user >= g->n)
        return SD_EBADID;
    if (used == user)
        return SD_OK;
    sd_edges *list = &g->adj[used];
    for (int32_t i = 0; i < list->len; i++) {
        sd_edge *e = &list->items[i];
        if (e->to == user) {
            if (certain && !e->certain) {
                e->certain = 1;
                e->line = line;
            }
            return SD_OK;
        }
    }
    if (list->len == list->cap) {
        sd_edge *p = grow(list->items, &list->cap, list->len + 1, sizeof *list->items);
        if (!p)
            return SD_ENOMEM;
        list->items = p;
    }
    list->items[list->len++] = (sd_edge){user, line, certain ? 1 : 0};
    g->edges++;
    return SD_OK;
}

static int push(sd_hits *out, int32_t node, int32_t depth, int32_t line, int certain) {
    if (out->len == out->cap) {
        sd_hit *p = grow(out->items, &out->cap, out->len + 1, sizeof *out->items);
        if (!p)
            return SD_ENOMEM;
        out->items = p;
    }
    out->items[out->len++] = (sd_hit){node, depth, line, certain ? 1 : 0};
    return SD_OK;
}

int sd_graph_trace(const sd_graph *g, const int32_t *origins, int32_t n_origins,
                   const sd_hit *seeds, int32_t n_seeds, int32_t max_depth, sd_hits *out) {
    out->len = 0;
    for (int32_t i = 0; i < n_origins; i++)
        if (origins[i] < 0 || origins[i] >= g->n)
            return SD_EBADID;
    for (int32_t i = 0; seeds && i < n_seeds; i++)
        if (seeds[i].node < 0 || seeds[i].node >= g->n)
            return SD_EBADID;
    if (max_depth == 0)
        return SD_OK;

    uint8_t *seen = calloc(g->n ? (size_t)g->n : 1, 1);
    if (!seen)
        return SD_ENOMEM;
    int rc = SD_OK;
    for (int32_t i = 0; i < n_origins; i++)
        seen[origins[i]] = 1;

    if (seeds) {
        for (int32_t i = 0; i < n_seeds && rc == SD_OK; i++) {
            if (seen[seeds[i].node])
                continue;
            seen[seeds[i].node] = 1;
            rc = push(out, seeds[i].node, 1, seeds[i].line, seeds[i].certain);
        }
    } else {
        for (int32_t i = 0; i < n_origins && rc == SD_OK; i++) {
            const sd_edges *list = &g->adj[origins[i]];
            for (int32_t j = 0; j < list->len && rc == SD_OK; j++) {
                const sd_edge *e = &list->items[j];
                if (seen[e->to])
                    continue;
                seen[e->to] = 1;
                rc = push(out, e->to, 1, e->line, e->certain);
            }
        }
    }

    /* результаты одного уровня лежат подряд: [start, end) и есть фронт */
    int32_t start = 0, end = out->len, depth = 1;
    while (rc == SD_OK && start < end && (max_depth < 0 || depth < max_depth)) {
        depth++;
        for (int32_t i = start; i < end && rc == SD_OK; i++) {
            int32_t node = out->items[i].node; /* копии: push может перенести буфер */
            int certain = out->items[i].certain;
            const sd_edges *list = &g->adj[node];
            for (int32_t j = 0; j < list->len && rc == SD_OK; j++) {
                const sd_edge *e = &list->items[j];
                if (seen[e->to])
                    continue;
                seen[e->to] = 1;
                rc = push(out, e->to, depth, e->line, certain && e->certain);
            }
        }
        start = end;
        end = out->len;
    }
    free(seen);
    return rc;
}

void sd_hits_free(sd_hits *hits) {
    free(hits->items);
    memset(hits, 0, sizeof *hits);
}
