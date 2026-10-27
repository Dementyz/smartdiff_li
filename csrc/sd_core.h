/* Ядро SmartDiff: граф зависимостей, обход влияния, сигнатуры, риск.
 * Чистый C11 без зависимостей от Python; обёртка для CPython в pymodule.c. */
#ifndef SD_CORE_H
#define SD_CORE_H

#include <stddef.h>
#include <stdint.h>

#define SD_OK 0
#define SD_ENOMEM (-1)
#define SD_EBADID (-2)

/* ---- граф ---- */

typedef struct {
    int32_t to;      /* кто использует узел */
    int32_t line;    /* строка, где стоит ссылка */
    uint8_t certain; /* 1: точная ссылка, 0: вероятная */
} sd_edge;

typedef struct {
    sd_edge *items;
    int32_t len, cap;
} sd_edges;

/* Обратный граф: adj[used] хранит всех, кто использует used. */
typedef struct {
    sd_edges *adj;
    int32_t n, cap;
    int64_t edges;
} sd_graph;

typedef struct {
    int32_t node;
    int32_t depth;
    int32_t line;
    uint8_t certain;
} sd_hit;

typedef struct {
    sd_hit *items;
    int32_t len, cap;
} sd_hits;

void sd_graph_init(sd_graph *g);
void sd_graph_free(sd_graph *g);
/* Добавляет count узлов, возвращает id первого или SD_ENOMEM. */
int32_t sd_graph_add_nodes(sd_graph *g, int32_t count);
/* user использует used. Повторное ребро не дублируется, но может стать точным. */
int sd_graph_add_edge(sd_graph *g, int32_t used, int32_t user, int certain, int32_t line);

/* Обход в ширину от origins. Если seeds != NULL, они задают первый уровень
 * (поле depth игнорируется), иначе первый уровень берётся из рёбер origins.
 * max_depth < 0: без ограничения. Результат в порядке обхода; точность
 * накапливается по пути (точно только если все рёбра пути точные). */
int sd_graph_trace(const sd_graph *g, const int32_t *origins, int32_t n_origins,
                   const sd_hit *seeds, int32_t n_seeds, int32_t max_depth, sd_hits *out);
void sd_hits_free(sd_hits *hits);

/* ---- сигнатуры ---- */

enum { SD_POSONLY, SD_POSITIONAL, SD_VARARG, SD_KWONLY, SD_KWARG };

typedef struct {
    const char *name;
    int kind;
    int has_default;
} sd_param;

/* 1, если новая сигнатура ломает существующие вызовы. */
int sd_signature_break(const sd_param *old, size_t n_old, const sd_param *new_, size_t n_new);

/* ---- риск ---- */

enum { SD_ADDED, SD_REMOVED, SD_BODY, SD_SIGNATURE, SD_DOC, SD_MOVED };

typedef struct {
    int change;
    int breaking;
    int is_public;
    int is_test;
    int32_t direct;
    int32_t total;
    int32_t broken;
} sd_change_info;

double sd_change_score(const sd_change_info *c);
const char *sd_level_for(double score);

#endif
