import json
import time
from pathlib import Path
from typing import Callable
import httpx

_RETRYABLE = {429, 500, 502, 503, 504}


class DriveUploader:
    def __init__(
        self,
        http: httpx.Client,
        token_provider: Callable[[], str],
        folder_id: str | None = None,
        sleep: Callable = time.sleep,
    ):
        self.http = http
        self.token_provider = token_provider
        self.folder_id = folder_id
        self.sleep = sleep

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self.token_provider()}'}

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        response = self.http.request(method, url, **kw)
        attempt = 0
        while response.status_code in _RETRYABLE and attempt < 3:
            attempt += 1
            self.sleep(0.5 * (2 ** (attempt - 1)))
            response = self.http.request(method, url, **kw)
        response.raise_for_status()
        return response

    def _find_existing(self, name: str) -> str | None:
        q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and trashed = false"
        if self.folder_id:
            q += f" and '{self.folder_id}' in parents"
        else:
            q += " and 'root' in parents"
        from urllib.parse import urlencode
        url = (
            'https://www.googleapis.com/drive/v3/files?'
            + urlencode({'q': q, 'fields': 'files(id,webViewLink)'})
        )
        response = self._request('GET', url, headers=self._headers())
        files = response.json().get('files', [])
        if files:
            return files[0].get('webViewLink') or (
                f"https://drive.google.com/file/d/{files[0]['id']}/view")
        return None

    def upload_png(self, path: Path, name: str) -> str:
        existing = self._find_existing(name)
        if existing:
            return existing

        metadata: dict = {'name': name, 'mimeType': 'image/png'}
        if self.folder_id:
            metadata['parents'] = [self.folder_id]
        boundary = 'tea-drive-upload-boundary'
        body = (
            f'--{boundary}\r\n'
            f'Content-Type: application/json; charset=UTF-8\r\n\r\n'
            f'{json.dumps(metadata)}\r\n'
            f'--{boundary}\r\n'
            f'Content-Type: image/png\r\n\r\n'
        ).encode() + path.read_bytes() + f'\r\n--{boundary}--'.encode()

        url = (
            'https://www.googleapis.com/upload/drive/v3/files'
            '?uploadType=multipart&fields=id,webViewLink'
        )
        headers = self._headers()
        headers['Content-Type'] = f'multipart/related; boundary={boundary}'
        response = self._request('POST', url, headers=headers, content=body)
        data = response.json()
        return data.get('webViewLink') or (
            f"https://drive.google.com/file/d/{data['id']}/view")
