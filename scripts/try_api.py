#!/usr/bin/env python3
"""Разведка живого API на сервере (план, задача 2; ТЗ, раздел 21 «Проверить на разведке»).

Запуск — на сервере, из папки бота, с переменными из .env (ключ и токен на Мак не попадают):

  set -a && . ./.env && set +a
  python3 -B scripts/try_api.py youtube --channel UC… --handle @имя --cyrillic-handle @имя \
      --legacy https://www.youtube.com/c/Имя --legacy https://www.youtube.com/Имя --user Имя \
      --empty-channel UC… --premiere <ID видео>
  python3 -B scripts/try_api.py telegram

Печатает только поведение API: статусы, reason, есть ли поля, сколько запросов ушло. Названия, описания, цифры
и адреса каналов не печатает и никуда не пишет (ТЗ, Сек13): записанные ответы — тоже данные YouTube.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True

API = "https://www.googleapis.com/youtube/v3/"
TELEGRAM = "https://api.telegram.org/bot{token}/{method}"
KEY_HEADER = "X-goog-api-key"
TIMEOUT_SECONDS = 20
PAGES_MAX = 4
BATCH = 50
OVER_BATCH = 51
UNKNOWN_HANDLE = "@jw-razvedka-net-takogo-" + uuid.uuid4().hex[:8]
STAND_IN_PICTURE = Path(__file__).resolve().parents[1] / "_avatars" / "jw-video-channel-audit-cover-640x360.png"
FIELDS = {
    "channels": "items(id,snippet(title,description,customUrl),contentDetails/relatedPlaylists/uploads)",
    "video_channel": "items/snippet/channelId",
    "page": "nextPageToken,items/contentDetails(videoId,videoPublishedAt)",
    "videos": ("items(id,snippet(publishedAt,title,description,liveBroadcastContent),contentDetails/duration,"
               "statistics/viewCount,liveStreamingDetails)"),
}
REQUESTS = Counter()


def skeleton(value):
    """Форма ответа без значений: ключи и типы — по ней пишутся выдуманные тестовые ответы."""
    if isinstance(value, dict):
        return {key: skeleton(item) for key, item in value.items()}
    if isinstance(value, list):
        return [skeleton(value[0])] if value else []
    if isinstance(value, bool):
        return "bool"
    if value is None:
        return "null"
    return "number" if isinstance(value, (int, float)) else "str"


def multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
             for name, value in fields.items()]
    header = (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
              f"Content-Type: image/png\r\n\r\n").encode()
    body = b"".join(parts) + header + file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def youtube(method: str, params: dict[str, str], use_header: bool = True) -> tuple[int, dict]:
    REQUESTS[method] += 1
    key = os.environ["YOUTUBE_API_KEY"]
    query = dict(params) if use_header else {**params, "key": key}
    request = urllib.request.Request(API + method + "?" + urllib.parse.urlencode(query),
                                     headers={KEY_HEADER: key} if use_header else {})
    return _open(request)


def _open(request: urllib.request.Request) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, _json_or_empty(error.read())


def _json_or_empty(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def reason(payload: dict) -> str:
    errors = (payload.get("error") or {}).get("errors") or [{}]
    return str(errors[0].get("reason", "")) or "—"


def report(title: str, status: int, payload: dict, extra: str = "") -> None:
    items = payload.get("items")
    count = "нет items" if items is None else f"items: {len(items)}"
    print(f"{title}: HTTP {status}, reason {reason(payload)}, {count}{extra}")


def channel_by(parameter: str, value: str) -> tuple[int, dict]:
    return youtube("channels", {"part": "snippet,contentDetails", parameter: value, "fields": FIELDS["channels"]})


def check_key_and_fields(channel_id: str, shapes: bool) -> str | None:
    status, payload = youtube("channels", {"part": "id", "id": channel_id}, use_header=True)
    report("ключ в заголовке X-goog-api-key", status, payload)
    status, payload = youtube("channels", {"part": "id", "id": channel_id}, use_header=False)
    report("ключ параметром key", status, payload)
    status, payload = channel_by("id", channel_id)
    report("fields channels.list", status, payload)
    if shapes:
        print("  форма:", json.dumps(skeleton(payload), ensure_ascii=False))
    items = payload.get("items") or [{}]
    return ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")


def check_handles(handles: list[str]) -> None:
    for handle in handles:
        bare = handle.removeprefix("@")
        results = {variant: channel_by("forHandle", variant) for variant in (handle, bare, bare.upper())}
        ids = {variant: ((payload.get("items") or [{}])[0].get("id")) for variant, (_, payload) in results.items()}
        print(f"forHandle: с @ / без @ / ВЕРХНИЙ РЕГИСТР — один канал: {len(set(ids.values())) == 1}, "
              f"найден: {all(ids.values())}")
    status, payload = channel_by("forHandle", UNKNOWN_HANDLE)
    report("forHandle несуществующего имени", status, payload)


def check_cyrillic(handle: str | None) -> None:
    if handle:
        status, payload = channel_by("forHandle", handle)
        report("forHandle на кириллице", status, payload)


def check_legacy(urls: list[str], users: list[str]) -> None:
    for url in urls:
        name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.strip("/").split("/")[-1])
        found_handle = bool(channel_by("forHandle", name)[1].get("items"))
        found_user = bool(channel_by("forUsername", name)[1].get("items"))
        kind = "/c/" if "/c/" in url else "/ИМЯ"
        print(f"старый адрес {kind}: forHandle нашёл — {found_handle}, forUsername нашёл — {found_user}")
    for user in users:
        status, payload = channel_by("forUsername", user)
        report("forUsername (/user/)", status, payload)


def check_uploads(uploads: str | None, shapes: bool) -> list[str]:
    if not uploads:
        print("плейлиста загрузок нет — проверить --channel")
        return []
    ids, dates, token, missing_dates = [], [], None, 0
    for _ in range(PAGES_MAX):
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": str(BATCH), "fields": FIELDS["page"]}
        status, payload = youtube("playlistItems", {**params, **({"pageToken": token} if token else {})})
        if shapes and not ids:
            print("  форма страницы:", json.dumps(skeleton(payload), ensure_ascii=False))
        for item in payload.get("items") or []:
            details = item.get("contentDetails") or {}
            missing_dates += "videoPublishedAt" not in details
            ids.append(details.get("videoId"))
            dates.append(details.get("videoPublishedAt") or "")
        token = payload.get("nextPageToken")
        if not token:
            break
    known = [date for date in dates if date]
    print(f"плейлист загрузок: видео {len(ids)}, без videoPublishedAt {missing_dates}, "
          f"nextPageToken приходит: {token is not None or len(ids) < BATCH}, "
          f"порядок по дате: {known == sorted(known, reverse=True)}")
    return [video_id for video_id in ids if video_id]


def check_videos(ids: list[str], shapes: bool) -> None:
    broadcast, live, zero, no_views, privacy = Counter(), 0, 0, 0, Counter()
    for start in range(0, len(ids), BATCH):
        batch = ",".join(ids[start:start + BATCH])
        status, payload = youtube("videos", {"part": "snippet,contentDetails,statistics,liveStreamingDetails",
                                             "id": batch, "fields": FIELDS["videos"]})
        if shapes and start == 0:
            print("  форма videos.list:", json.dumps(skeleton(payload), ensure_ascii=False))
        for item in payload.get("items") or []:
            broadcast[(item.get("snippet") or {}).get("liveBroadcastContent")] += 1
            live += "liveStreamingDetails" in item
            zero += (item.get("contentDetails") or {}).get("duration") == "P0D"
            no_views += "viewCount" not in (item.get("statistics") or {})
        privacy.update(_privacy(batch))
    print(f"videos.list: liveBroadcastContent {dict(broadcast)}, с liveStreamingDetails {live}, "
          f"длительность P0D {zero}, без viewCount {no_views}; privacyStatus {dict(privacy)}")


def _privacy(batch: str) -> Counter:
    status, payload = youtube("videos", {"part": "status", "id": batch, "fields": "items/status/privacyStatus"})
    return Counter((item.get("status") or {}).get("privacyStatus") for item in payload.get("items") or [])


def check_limits(ids: list[str], channel_id: str, empty_channel: str | None, premiere: str | None) -> None:
    if len(ids) >= OVER_BATCH:
        status, payload = youtube("videos", {"part": "id", "id": ",".join(ids[:OVER_BATCH])})
        report("videos.list с 51 ID", status, payload)
    status, payload = youtube("channels", {"part": "brandingSettings", "id": channel_id})
    settings = ((payload.get("items") or [{}])[0].get("brandingSettings") or {}).get("channel") or {}
    print(f"brandingSettings.channel — ключи: {sorted(settings)}")
    if empty_channel:
        uploads = "UU" + empty_channel[2:]
        status, payload = youtube("playlistItems", {"part": "contentDetails", "playlistId": uploads})
        report("пустой плейлист загрузок", status, payload)
    if premiere:
        status, payload = youtube("videos", {"part": "snippet,liveStreamingDetails", "id": premiere})
        item = (payload.get("items") or [{}])[0]
        print(f"премьера: liveStreamingDetails есть — {'liveStreamingDetails' in item}, "
              f"liveBroadcastContent — {(item.get('snippet') or {}).get('liveBroadcastContent')}")


def run_youtube(args: argparse.Namespace) -> None:
    uploads = check_key_and_fields(args.channel, args.shapes)
    check_handles(args.handle)
    check_cyrillic(args.cyrillic_handle)
    check_legacy(args.legacy, args.user)
    ids = check_uploads(uploads, args.shapes)
    check_videos(ids, args.shapes)
    check_limits(ids, args.channel, args.empty_channel, args.premiere)
    print(f"запросов по методам: {dict(REQUESTS)}; всего {sum(REQUESTS.values())} (каждый — не меньше единицы)")


def telegram(method: str, payload: dict | None = None, body: bytes | None = None,
             content_type: str = "application/json") -> dict:
    url = TELEGRAM.format(token=os.environ["BOT_TOKEN"], method=method)
    data = body if body is not None else json.dumps(payload or {}).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": content_type})
    return _open(request)[1]


def run_telegram(_args: argparse.Namespace) -> None:
    admin = os.environ["ADMIN_ID"]
    body, content_type = multipart({"chat_id": admin, "disable_notification": "true"}, "photo", STAND_IN_PICTURE)
    sent = telegram("sendPhoto", body=body, content_type=content_type)
    file_id = sent["result"]["photo"][-1]["file_id"] if sent.get("ok") else None
    print(f"sendPhoto владельцу: ok — {sent.get('ok')}")
    photo = {"type": "photo", "photo": {"type": "photo", "media": file_id}}
    keyboard = {"inline_keyboard": [[{"text": "Проверка", "callback_data": "again"}]]}
    signature = {"type": "paragraph", "text": [{"type": "italic", "text": "разведка: подпись курсивом"}]}
    article = {"blocks": [photo, {"type": "paragraph", "text": "разведка: фото-блок по file_id из sendPhoto"},
                          signature]}
    rich = telegram("sendRichMessage", {"chat_id": admin, "rich_message": article, "reply_markup": keyboard})
    print(f"sendRichMessage с фото-блоком и курсивом: ok — {rich.get('ok')}, {rich.get('description', '')}")
    if rich.get("ok"):
        article["blocks"][1]["text"] = "разведка: правка статьи с фото-блоком"
        edit = telegram("editMessageText", {"chat_id": admin, "message_id": rich["result"]["message_id"],
                                            "rich_message": article, "reply_markup": keyboard})
        print(f"editMessageText с фото-блоком: ok — {edit.get('ok')}, {edit.get('description', '')}")
    if sent.get("ok"):
        telegram("deleteMessage", {"chat_id": admin, "message_id": sent["result"]["message_id"]})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    youtube_args = commands.add_parser("youtube")
    youtube_args.add_argument("--channel", required=True, help="ID канала UC… с 50+ видео, трансляциями, короткими")
    youtube_args.add_argument("--handle", action="append", default=[], help="@имя (можно несколько)")
    youtube_args.add_argument("--cyrillic-handle")
    youtube_args.add_argument("--legacy", action="append", default=[], help="старый адрес /c/Имя или /Имя")
    youtube_args.add_argument("--user", action="append", default=[], help="старое имя из /user/Имя")
    youtube_args.add_argument("--empty-channel", help="ID канала без открытых видео")
    youtube_args.add_argument("--premiere", help="ID видео, вышедшего премьерой")
    youtube_args.add_argument("--shapes", action="store_true", help="печатать форму ответов без значений")
    youtube_args.set_defaults(run=run_youtube)
    commands.add_parser("telegram").set_defaults(run=run_telegram)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    arguments.run(arguments)
