"""`core`: tham chiếu tới module main.py cho các file *_routes.py và prod_plan_sync.py.

main.py gọi `app_core.bind(sys.modules[__name__])` TRƯỚC khi import các module đó.
`core.<tên>` được tra lúc chạy trên module bind sau cùng, vì:
- test patch `main.<tên>` vẫn có hiệu lực;
- khi chạy `python main.py` (reload trên Windows), main.py bị nạp 2 lần trong tiến trình
  worker (`__mp_main__` rồi `main`); `core` luôn trỏ tới bản `main` đang phục vụ request.
"""
from types import ModuleType
from typing import Any, Optional


class _CoreProxy:
    __slots__ = ("_module",)

    def __init__(self) -> None:
        object.__setattr__(self, "_module", None)

    def __getattr__(self, name: str) -> Any:
        module: Optional[ModuleType] = object.__getattribute__(self, "_module")
        if module is None:
            raise RuntimeError("app_core.bind(main) chưa được gọi")
        return getattr(module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Gán giá trị trên module main, không gán qua core")

    def __repr__(self) -> str:
        return f"<core -> {object.__getattribute__(self, '_module')!r}>"


core = _CoreProxy()


def bind(module: ModuleType) -> None:
    object.__setattr__(core, "_module", module)
