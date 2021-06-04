import contextlib
import IPython
import os


def set_error_handling(verbosity):
    ipython = IPython.get_ipython()
    if ipython is not None:
        with open(os.devnull, "w") as ignore, contextlib.redirect_stdout(ignore):
            ipython.magic(f"xmode {verbosity}")
