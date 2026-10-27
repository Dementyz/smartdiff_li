/* Обёртка ядра для CPython: модуль smartdiff_li._core. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>

#include "sd_core.h"

static int raise_status(int rc) {
    if (rc == SD_ENOMEM)
        PyErr_NoMemory();
    else if (rc == SD_EBADID)
        PyErr_SetString(PyExc_IndexError, "node id out of range");
    return -1;
}

static int to_int32(PyObject *obj, int32_t *out) {
    long value = PyLong_AsLong(obj);
    if (value == -1 && PyErr_Occurred())
        return -1;
    if (value < INT32_MIN || value > INT32_MAX) {
        PyErr_SetString(PyExc_OverflowError, "value does not fit in int32");
        return -1;
    }
    *out = (int32_t)value;
    return 0;
}

/* ---- Graph ---- */

typedef struct {
    PyObject_HEAD
    sd_graph g;
} GraphObject;

static void Graph_dealloc(GraphObject *self) {
    sd_graph_free(&self->g);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static int Graph_init(GraphObject *self, PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"nodes", NULL};
    int nodes = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|i", kwlist, &nodes))
        return -1;
    sd_graph_free(&self->g);
    if (nodes < 0) {
        PyErr_SetString(PyExc_ValueError, "nodes must be >= 0");
        return -1;
    }
    if (nodes > 0 && sd_graph_add_nodes(&self->g, nodes) < 0)
        return raise_status(SD_ENOMEM);
    return 0;
}

static PyObject *Graph_add_nodes(GraphObject *self, PyObject *arg) {
    int32_t count;
    if (to_int32(arg, &count) < 0)
        return NULL;
    if (count < 0) {
        PyErr_SetString(PyExc_ValueError, "count must be >= 0");
        return NULL;
    }
    int32_t first = sd_graph_add_nodes(&self->g, count);
    if (first < 0)
        return raise_status(first), NULL;
    return PyLong_FromLong(first);
}

static PyObject *Graph_add_node(GraphObject *self, PyObject *Py_UNUSED(ignored)) {
    int32_t id = sd_graph_add_nodes(&self->g, 1);
    if (id < 0)
        return raise_status(id), NULL;
    return PyLong_FromLong(id);
}

static PyObject *Graph_add_edge(GraphObject *self, PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"used", "user", "certain", "line", NULL};
    int used, user, certain = 1, line = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "ii|pi", kwlist, &used, &user, &certain, &line))
        return NULL;
    int rc = sd_graph_add_edge(&self->g, used, user, certain, line);
    if (rc != SD_OK)
        return raise_status(rc), NULL;
    Py_RETURN_NONE;
}

static PyObject *Graph_users(GraphObject *self, PyObject *arg) {
    int32_t node;
    if (to_int32(arg, &node) < 0)
        return NULL;
    if (node < 0 || node >= self->g.n)
        return raise_status(SD_EBADID), NULL;
    const sd_edges *list = &self->g.adj[node];
    PyObject *result = PyList_New(list->len);
    if (!result)
        return NULL;
    for (int32_t i = 0; i < list->len; i++) {
        const sd_edge *e = &list->items[i];
        PyObject *item = Py_BuildValue("(iNi)", e->to, PyBool_FromLong(e->certain), e->line);
        if (!item) {
            Py_DECREF(result);
            return NULL;
        }
        PyList_SET_ITEM(result, i, item);
    }
    return result;
}

static int read_nodes(PyObject *seq_obj, int32_t **out, Py_ssize_t *n) {
    PyObject *seq = PySequence_Fast(seq_obj, "origins must be a sequence of ints");
    if (!seq)
        return -1;
    *n = PySequence_Fast_GET_SIZE(seq);
    *out = PyMem_Malloc((size_t)(*n ? *n : 1) * sizeof **out);
    if (!*out) {
        Py_DECREF(seq);
        PyErr_NoMemory();
        return -1;
    }
    for (Py_ssize_t i = 0; i < *n; i++) {
        if (to_int32(PySequence_Fast_GET_ITEM(seq, i), &(*out)[i]) < 0) {
            PyMem_Free(*out);
            Py_DECREF(seq);
            return -1;
        }
    }
    Py_DECREF(seq);
    return 0;
}

static int read_seeds(PyObject *seq_obj, sd_hit **out, Py_ssize_t *n) {
    PyObject *seq = PySequence_Fast(seq_obj, "seeds must be a sequence of (node, certain, line)");
    if (!seq)
        return -1;
    *n = PySequence_Fast_GET_SIZE(seq);
    *out = PyMem_Malloc((size_t)(*n ? *n : 1) * sizeof **out);
    if (!*out) {
        Py_DECREF(seq);
        PyErr_NoMemory();
        return -1;
    }
    for (Py_ssize_t i = 0; i < *n; i++) {
        int node, certain, line;
        PyObject *item = PySequence_Fast_GET_ITEM(seq, i);
        if (!PyTuple_Check(item) || !PyArg_ParseTuple(item, "ipi", &node, &certain, &line)) {
            if (!PyErr_Occurred())
                PyErr_SetString(PyExc_TypeError, "seed must be a (node, certain, line) tuple");
            PyMem_Free(*out);
            Py_DECREF(seq);
            return -1;
        }
        (*out)[i] = (sd_hit){node, 1, line, certain ? 1 : 0};
    }
    Py_DECREF(seq);
    return 0;
}

static PyObject *Graph_trace(GraphObject *self, PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"origins", "depth", "seeds", NULL};
    PyObject *origins_obj, *seeds_obj = Py_None;
    int depth = -1;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|iO", kwlist, &origins_obj, &depth, &seeds_obj))
        return NULL;

    int32_t *origins = NULL;
    sd_hit *seeds = NULL;
    Py_ssize_t n_origins = 0, n_seeds = 0;
    if (read_nodes(origins_obj, &origins, &n_origins) < 0)
        return NULL;
    if (seeds_obj != Py_None && read_seeds(seeds_obj, &seeds, &n_seeds) < 0) {
        PyMem_Free(origins);
        return NULL;
    }
    if (n_origins > INT32_MAX || n_seeds > INT32_MAX) {
        PyMem_Free(origins);
        PyMem_Free(seeds);
        return raise_status(SD_ENOMEM), NULL;
    }

    /* GIL не отпускаем: другой поток мог бы менять граф во время обхода */
    sd_hits hits = {0};
    int rc = sd_graph_trace(&self->g, origins, (int32_t)n_origins, seeds, (int32_t)n_seeds, depth, &hits);
    PyMem_Free(origins);
    PyMem_Free(seeds);
    if (rc != SD_OK) {
        sd_hits_free(&hits);
        return raise_status(rc), NULL;
    }

    PyObject *result = PyList_New(hits.len);
    for (int32_t i = 0; result && i < hits.len; i++) {
        const sd_hit *h = &hits.items[i];
        PyObject *item = Py_BuildValue("(iiNi)", h->node, h->depth, PyBool_FromLong(h->certain), h->line);
        if (!item)
            Py_CLEAR(result);
        else
            PyList_SET_ITEM(result, i, item);
    }
    sd_hits_free(&hits);
    return result;
}

static PyObject *Graph_reachable(GraphObject *self, PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"origin", "depth", NULL};
    int origin, depth = -1;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "i|i", kwlist, &origin, &depth))
        return NULL;
    int32_t start = origin;
    sd_hits hits = {0};
    int rc = sd_graph_trace(&self->g, &start, 1, NULL, 0, depth, &hits);
    if (rc != SD_OK) {
        sd_hits_free(&hits);
        return raise_status(rc), NULL;
    }
    PyObject *result = PyDict_New();
    for (int32_t i = 0; result && i < hits.len; i++) {
        PyObject *key = PyLong_FromLong(hits.items[i].node);
        PyObject *value = PyLong_FromLong(hits.items[i].depth);
        if (!key || !value || PyDict_SetItem(result, key, value) < 0)
            Py_CLEAR(result);
        Py_XDECREF(key);
        Py_XDECREF(value);
    }
    sd_hits_free(&hits);
    return result;
}

static Py_ssize_t Graph_len(GraphObject *self) { return self->g.n; }

static PyObject *Graph_edge_count(GraphObject *self, void *Py_UNUSED(closure)) {
    return PyLong_FromLongLong(self->g.edges);
}

static PyMethodDef Graph_methods[] = {
    {"add_node", (PyCFunction)Graph_add_node, METH_NOARGS, "Add a node, return its id."},
    {"add_nodes", (PyCFunction)Graph_add_nodes, METH_O, "Add count nodes, return the first id."},
    {"add_edge", (PyCFunction)(void (*)(void))Graph_add_edge, METH_VARARGS | METH_KEYWORDS,
     "add_edge(used, user, certain=True, line=0): user depends on used."},
    {"users", (PyCFunction)Graph_users, METH_O, "users(node) -> [(user, certain, line)]"},
    {"trace", (PyCFunction)(void (*)(void))Graph_trace, METH_VARARGS | METH_KEYWORDS,
     "trace(origins, depth=-1, seeds=None) -> [(node, depth, certain, line)]"},
    {"reachable", (PyCFunction)(void (*)(void))Graph_reachable, METH_VARARGS | METH_KEYWORDS,
     "reachable(origin, depth=-1) -> {node: distance}"},
    {0},
};

static PyGetSetDef Graph_getset[] = {
    {"edge_count", (getter)Graph_edge_count, NULL, "number of edges", NULL},
    {0},
};

static PySequenceMethods Graph_as_sequence = {.sq_length = (lenfunc)Graph_len};

static PyTypeObject GraphType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "smartdiff_li._core.Graph",
    .tp_doc = "Reverse dependency graph: edges point from a node to its users.",
    .tp_basicsize = sizeof(GraphObject),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
    .tp_init = (initproc)Graph_init,
    .tp_dealloc = (destructor)Graph_dealloc,
    .tp_methods = Graph_methods,
    .tp_getset = Graph_getset,
    .tp_as_sequence = &Graph_as_sequence,
};

/* ---- функции ---- */

static int read_params(PyObject *seq_obj, PyObject **keep, sd_param **out, Py_ssize_t *n) {
    PyObject *seq = PySequence_Fast(seq_obj, "params must be a sequence of (name, kind, has_default)");
    if (!seq)
        return -1;
    *n = PySequence_Fast_GET_SIZE(seq);
    *out = PyMem_Malloc((size_t)(*n ? *n : 1) * sizeof **out);
    if (!*out) {
        Py_DECREF(seq);
        PyErr_NoMemory();
        return -1;
    }
    for (Py_ssize_t i = 0; i < *n; i++) {
        PyObject *item = PySequence_Fast_GET_ITEM(seq, i);
        sd_param *p = &(*out)[i];
        if (!PyTuple_Check(item) || !PyArg_ParseTuple(item, "sip", &p->name, &p->kind, &p->has_default)) {
            if (!PyErr_Occurred())
                PyErr_SetString(PyExc_TypeError, "param must be a (name, kind, has_default) tuple");
            PyMem_Free(*out);
            Py_DECREF(seq);
            return -1;
        }
    }
    *keep = seq; /* имена живут, пока жива последовательность */
    return 0;
}

static PyObject *signature_break(PyObject *Py_UNUSED(module), PyObject *args) {
    PyObject *old_obj, *new_obj, *old_seq = NULL, *new_seq = NULL;
    sd_param *old = NULL, *new_ = NULL;
    Py_ssize_t n_old, n_new;
    if (!PyArg_ParseTuple(args, "OO", &old_obj, &new_obj))
        return NULL;
    if (read_params(old_obj, &old_seq, &old, &n_old) < 0)
        return NULL;
    if (read_params(new_obj, &new_seq, &new_, &n_new) < 0) {
        PyMem_Free(old);
        Py_DECREF(old_seq);
        return NULL;
    }
    int result = sd_signature_break(old, (size_t)n_old, new_, (size_t)n_new);
    PyMem_Free(old);
    PyMem_Free(new_);
    Py_DECREF(old_seq);
    Py_DECREF(new_seq);
    return PyBool_FromLong(result);
}

static const char *const CHANGE_NAMES[] = {"added", "removed", "body", "signature", "doc", "moved"};

static PyObject *change_score(PyObject *Py_UNUSED(module), PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"change", "breaking", "public", "test", "direct", "total", "broken", NULL};
    const char *change;
    int breaking, public_, test, direct = 0, total = 0, broken = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "sppp|iii", kwlist, &change, &breaking,
                                     &public_, &test, &direct, &total, &broken))
        return NULL;
    int kind = -1;
    for (int i = 0; i < (int)(sizeof CHANGE_NAMES / sizeof *CHANGE_NAMES); i++)
        if (strcmp(change, CHANGE_NAMES[i]) == 0)
            kind = i;
    if (kind < 0) {
        PyErr_Format(PyExc_ValueError, "unknown change kind: %s", change);
        return NULL;
    }
    sd_change_info info = {kind, breaking, public_, test, direct, total, broken};
    return PyFloat_FromDouble(sd_change_score(&info));
}

static PyObject *level_for(PyObject *Py_UNUSED(module), PyObject *arg) {
    double score = PyFloat_AsDouble(arg);
    if (score == -1.0 && PyErr_Occurred())
        return NULL;
    return PyUnicode_FromString(sd_level_for(score));
}

static PyMethodDef module_methods[] = {
    {"signature_break", signature_break, METH_VARARGS,
     "signature_break(old, new) -> bool; params are (name, kind, has_default) tuples."},
    {"change_score", (PyCFunction)(void (*)(void))change_score, METH_VARARGS | METH_KEYWORDS,
     "change_score(change, breaking, public, test, direct=0, total=0, broken=0) -> float"},
    {"level_for", level_for, METH_O, "level_for(score) -> 'low' | 'medium' | 'high' | 'critical'"},
    {0},
};

static struct PyModuleDef core_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "smartdiff_li._core",
    .m_doc = "SmartDiff core written in C.",
    .m_size = -1,
    .m_methods = module_methods,
};

PyMODINIT_FUNC PyInit__core(void) {
    if (PyType_Ready(&GraphType) < 0)
        return NULL;
    PyObject *module = PyModule_Create(&core_module);
    if (!module)
        return NULL;
    if (PyModule_AddType(module, &GraphType) < 0) {
        Py_DECREF(module);
        return NULL;
    }
    return module;
}
