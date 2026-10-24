"""The character's allocated passives from pathofexile.com, the same public
endpoints Path of Building's character import uses. Needs the profile's
"Characters" tab to be public.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

HOST = "https://www.pathofexile.com/"
UA = "PoE-TreeOverlay/0.3 (passive tree overlay; screen reading only)"


class SiteError(Exception):
    pass


def normalise_account(name):
    """'Name-1234' and 'Name#1234' both mean the account with discriminator."""
    name = re.sub(r"\s+", "", name)
    return re.sub(r"^(.*)[#-](\d{4})$", r"\1#\2", name)


def _get(path, **params):
    url = HOST + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SiteError("The profile is private or doesn't exist. Make the Characters tab public on "
                            "pathofexile.com (Privacy Settings).") from exc
        if exc.code == 404:
            raise SiteError("Account name not found.") from exc
        if exc.code == 429:
            raise SiteError("pathofexile.com is rate limiting; try again in a minute.") from exc
        raise SiteError(f"pathofexile.com answered {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise SiteError(f"Can't reach pathofexile.com ({exc.reason}).") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise SiteError("pathofexile.com sent something unexpected.") from exc


def characters(account, realm="pc"):
    """[{name, league, class, level}, ...] of the account."""
    data = _get("character-window/get-characters", accountName=normalise_account(account), realm=realm)
    if isinstance(data, dict) and data.get("error"):
        raise SiteError(data["error"].get("message", "error"))
    return [{"name": c["name"], "league": c.get("league", ""), "class": c.get("class", ""),
             "level": c.get("level", 0)} for c in data]


def passives(account, character, realm="pc"):
    """(allocated node ids, {mastery node: effect}) of the character."""
    data = _get("character-window/get-passive-skills", accountName=normalise_account(account),
                character=character, realm=realm)
    return parse_passives(data)


def parse_passives(data):
    if isinstance(data, dict) and data.get("error"):
        raise SiteError(data["error"].get("message", "error"))
    p = data.get("passives", data)          # PoB wraps it, the site doesn't
    hashes = set(int(h) for h in p.get("hashes", []))
    masteries = {int(k): int(v) for k, v in (p.get("mastery_effects") or {}).items()}
    return hashes, masteries
