# Удаление отступов у текста
def ded(get_text: str) -> str:
    if get_text is not None:
        split_text = get_text.split("\n")

        if split_text[0] == "":
            split_text.pop(0)
        if split_text[-1] == "":
            split_text.pop(-1)
        save_text = []

        for text in split_text:
            while text.startswith(" "):
                text = text[1:]

            save_text.append(text)
        get_text = "\n".join(save_text)
    else:
        get_text = ""

    return get_text


# Очистка текста от HTML тэгов
def clear_html(get_text: str) -> str:
    if get_text is not None:
        if "<" in get_text:
            get_text = get_text.replace("<", "*")
        if ">" in get_text:
            get_text = get_text.replace(">", "*")
    else:
        get_text = ""

    return get_text


def format_display(fmt: str) -> str:
    """Перевод формата работы в человекопонятный вид"""
    mapping = {
        "hour": "⏱ Почасовая работа",
        "shift8": "🕗 Смена (8 часов)",
        "day12": "📅 Смена (12 часов)",
    }
    return mapping.get(fmt, fmt)
