"""Bounded MLX allocator; let launchd recover a dead inference thread."""
import os
import runpy
import threading

_original_thread_hook = threading.excepthook


def fatal_thread_error(args):
    _original_thread_hook(args)
    # MLX can leave HTTP alive after its generation thread dies. Exit the whole
    # process so launchd KeepAlive reloads the model instead of serving hangs.
    os._exit(1)


if __name__ == '__main__':
    import mlx.core as mx
    mx.set_cache_limit(128 * 1024 * 1024)
    threading.excepthook = fatal_thread_error
    runpy.run_module('mlx_lm.server', run_name='__main__')
