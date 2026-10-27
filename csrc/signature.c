#include <string.h>

#include "sd_core.h"

static const sd_param *find(const sd_param *params, size_t n, const char *name) {
    for (size_t i = 0; i < n; i++)
        if (strcmp(params[i].name, name) == 0)
            return &params[i];
    return NULL;
}

static int positional(const sd_param *p) {
    return p->kind == SD_POSONLY || p->kind == SD_POSITIONAL;
}

int sd_signature_break(const sd_param *old, size_t n_old, const sd_param *new_, size_t n_new) {
    for (size_t i = 0; i < n_old; i++) {
        const sd_param *q = find(new_, n_new, old[i].name);
        if (!q || q->kind != old[i].kind)
            return 1; /* параметр удалён, переименован или сменил вид */
        if (old[i].has_default && !q->has_default)
            return 1;
    }
    for (size_t i = 0; i < n_new; i++) {
        const sd_param *q = &new_[i];
        if (!find(old, n_old, q->name) && !q->has_default && q->kind != SD_VARARG && q->kind != SD_KWARG)
            return 1; /* новый обязательный параметр */
    }
    /* старые позиционные параметры должны остаться префиксом новых */
    size_t j = 0;
    for (size_t i = 0; i < n_old; i++) {
        if (!positional(&old[i]))
            continue;
        while (j < n_new && !positional(&new_[j]))
            j++;
        if (j == n_new || strcmp(new_[j].name, old[i].name) != 0)
            return 1;
        j++;
    }
    return 0;
}
