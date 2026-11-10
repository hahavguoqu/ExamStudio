"""Windows per-user encrypted credentials. API responses never contain the key."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data: bytes, decrypt=False) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    function = (ctypes.windll.crypt32.CryptUnprotectData if decrypt
                else ctypes.windll.crypt32.CryptProtectData)
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def path():
    return Path(os.environ["SHIJUAN_PROFILE"]) / "credential.bin"


def load():
    if path().exists():
        os.environ["DEEPSEEK_API_KEY"] = crypt(path().read_bytes(), True).decode("utf-8")


def save(key: str):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(crypt(key.encode("utf-8")))
    temporary.replace(target)
    os.environ["DEEPSEEK_API_KEY"] = key
