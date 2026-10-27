import sys

from setuptools import Extension, setup

# без FMA-сжатия: результаты C совпадают с Python бит в бит
compile_args = [] if sys.platform == "win32" else ["-std=c11", "-O2", "-ffp-contract=off"]

setup(
    ext_modules=[
        Extension(
            "smartdiff_li._core",
            sources=["csrc/pymodule.c", "csrc/graph.c", "csrc/signature.c", "csrc/risk.c"],
            include_dirs=["csrc"],
            extra_compile_args=compile_args,
            # нет компилятора: пакет ставится и работает на чистом Python
            optional=True,
        )
    ],
)
