from games.kintara.molten.view import format_snapshot


def format_ember_snapshot(snapshot, lang="fa"):
    return format_snapshot(snapshot, lang)


def format_ember_waiting(lang="fa"):
    return format_snapshot({}, lang)
