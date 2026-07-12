from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore(Protocol):
    def get(self, credential_id: str) -> str | None: ...

    def set(self, credential_id: str, secret: str) -> None: ...

    def delete(self, credential_id: str) -> None: ...


class MemoryCredentialStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get(self, credential_id: str) -> str | None:
        return self._secrets.get(credential_id)

    def set(self, credential_id: str, secret: str) -> None:
        if not secret:
            raise ValueError("API Key 不能为空")
        self._secrets[credential_id] = secret

    def delete(self, credential_id: str) -> None:
        self._secrets.pop(credential_id, None)


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    _GENERIC = 1
    _LOCAL_MACHINE = 2
    _NOT_FOUND = 1168

    def __init__(self, namespace: str = "AI-Novel-Studio") -> None:
        if sys.platform != "win32":
            raise CredentialStoreError("当前系统不支持 Windows 凭据管理器")
        self._namespace = namespace
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        pointer = ctypes.POINTER(_CredentialW)
        self._advapi32.CredWriteW.argtypes = [pointer, wintypes.DWORD]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(pointer),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    def _target(self, credential_id: str) -> str:
        if not credential_id.strip():
            raise ValueError("凭据 ID 不能为空")
        return f"{self._namespace}/{credential_id}"

    def get(self, credential_id: str) -> str | None:
        target = self._target(credential_id)
        pointer = ctypes.POINTER(_CredentialW)()
        if not self._advapi32.CredReadW(target, self._GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == self._NOT_FOUND:
                return None
            raise CredentialStoreError(f"读取系统凭据失败（错误码 {error}）")
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            self._advapi32.CredFree(pointer)

    def set(self, credential_id: str, secret: str) -> None:
        if not secret:
            raise ValueError("API Key 不能为空")
        target = self._target(credential_id)
        raw = secret.encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = _CredentialW()
        credential.Type = self._GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self._LOCAL_MACHINE
        credential.UserName = "AI Novel Studio"
        if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
            error = ctypes.get_last_error()
            raise CredentialStoreError(f"写入系统凭据失败（错误码 {error}）")

    def delete(self, credential_id: str) -> None:
        target = self._target(credential_id)
        if self._advapi32.CredDeleteW(target, self._GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self._NOT_FOUND:
            raise CredentialStoreError(f"删除系统凭据失败（错误码 {error}）")

