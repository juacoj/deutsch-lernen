import streamlit as st
import pandas as pd
import sqlite3
import random
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Deutsch Lernen",
    page_icon="🇩🇪",
    layout="centered"
)

DATA_FILE = Path("data/vocabulary_A1_B1_plus_100.xlsx")
DB_FILE = "progress.db"


# ============================================================
# ESTILOS
# ============================================================

st.markdown(
    """
    <style>
    .main-title {
        text-align: center;
        font-size: 42px;
        font-weight: 700;
        margin-bottom: 0;
    }

    .subtitle {
        text-align: center;
        color: #777;
        margin-bottom: 30px;
    }

    .question {
        font-size: 30px;
        font-weight: 600;
        text-align: center;
        padding: 20px;
    }

    .translation {
        text-align: center;
        color: #777;
        font-size: 18px;
    }

    .case-box {
        padding: 15px;
        border-radius: 10px;
        background-color: #f5f5f5;
        margin-top: 15px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# BASE DE DATOS
# ============================================================

def init_db():

    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            level TEXT,
            module TEXT,
            selected TEXT,
            expected TEXT,
            correct INTEGER,
            timestamp TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def save_answer(
    word,
    level,
    module,
    selected,
    expected,
    correct
):

    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT INTO answers
        (
            word,
            level,
            module,
            selected,
            expected,
            correct,
            timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            word,
            level,
            module,
            selected,
            expected,
            int(correct),
            datetime.now().isoformat()
        )
    )

    conn.commit()
    conn.close()


init_db()


# ============================================================
# CARGAR VOCABULARIO
# ============================================================

@st.cache_data
def load_vocabulary():

    if not DATA_FILE.exists():

        st.error(
            f"No encuentro el archivo:\n\n"
            f"`{DATA_FILE}`"
        )

        st.stop()

    df = pd.read_excel(
        DATA_FILE
    )

    # Asegurar columnas
    required_columns = [
        "id",
        "word",
        "article",
        "translation",
        "level",
        "category",
        "plural",
        "example_de",
        "example_es",
        "has_article",
        "part_of_speech",
        "preteritum",
        "partizip_II"
    ]

    for column in required_columns:

        if column not in df.columns:
            df[column] = ""

    # Convertir todo a texto para evitar problemas
    for column in required_columns:

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    return df


df = load_vocabulary()


# ============================================================
# NORMALIZACIÓN
# ============================================================

def normalize(text):

    if text is None:
        return ""

    return (
        str(text)
        .strip()
        .lower()
        .replace("ß", "ß")
    )


# ============================================================
# SESSION STATE
# ============================================================

defaults = {

    "module": "Artículos",

    "level": "Todos",

    "current_word": None,

    "answered": False,

    "last_correct": False,

    "last_answer": "",

    "score": 0,

    "total": 0,

    "answer_text": "",

    "case_answer_text": "",

    "past_answer_text": ""
}

for key, value in defaults.items():

    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# NUEVA PREGUNTA
# ============================================================

def reset_question(data):

    if data.empty:
        return

    selected = data.sample(1).iloc[0].to_dict()

    st.session_state.current_word = selected

    st.session_state.answered = False

    st.session_state.last_correct = False

    st.session_state.last_answer = ""

    st.session_state.answer_text = ""

    st.session_state.case_answer_text = ""

    st.session_state.past_answer_text = ""


# ============================================================
# TECLADO ALEMÁN
# ============================================================

def german_keyboard(state_key):

    st.caption("Caracteres alemanes")

    chars = [
        "ä",
        "ö",
        "ü",
        "Ä",
        "Ö",
        "Ü",
        "ß"
    ]

    columns = st.columns(7)

    for column, char in zip(columns, chars):

        with column:

            if st.button(
                char,
                key=f"{state_key}_{char}"
            ):

                st.session_state[state_key] += char

                st.rerun()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("🇩🇪 Deutsch Lernen")

module = st.sidebar.radio(
    "Módulo",
    [
        "Artículos",
        "Vocabulario",
        "Plurales",
        "Präteritum",
        "Casos"
    ]
)

level = st.sidebar.selectbox(
    "Nivel",
    [
        "Todos",
        "A1",
        "A2",
        "B1"
    ]
)

st.session_state.module = module
st.session_state.level = level


# ============================================================
# FILTRAR NIVEL
# ============================================================

if level == "Todos":

    filtered = df.copy()

else:

    filtered = df[
        df["level"] == level
    ].copy()


# ============================================================
# CABECERA
# ============================================================

st.markdown(
    '<div class="main-title">🇩🇪 Deutsch Lernen</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">'
    'Aprende alemán de A1 a B1'
    '</div>',
    unsafe_allow_html=True
)


# ============================================================
# MÓDULO 1 — ARTÍCULOS
# ============================================================

if module == "Artículos":

    article_words = filtered[
        (
            filtered["part_of_speech"]
            .str.lower()
            .str.strip()
            == "noun"
        )
        &
        (
            filtered["article"]
            .isin(["der", "die", "das"])
        )
    ].copy()

    if article_words.empty:

        st.warning(
            "No hay palabras disponibles."
        )

        st.stop()

    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word["word"]
        not in article_words["word"].values
    ):

        reset_question(article_words)

    word = st.session_state.current_word

    st.subheader("🔤 ¿Qué artículo lleva?")

    st.markdown(
        f'<div class="question">{word["word"]}</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        f'<div class="translation">'
        f'🇪🇸 {word["translation"]}'
        f'</div>',
        unsafe_allow_html=True
    )

    if not st.session_state.answered:

        columns = st.columns(3)

        for column, article in zip(
            columns,
            ["der", "die", "das"]
        ):

            with column:

                if st.button(
                    article,
                    use_container_width=True
                ):

                    correct = (
                        article
                        == word["article"]
                    )

                    st.session_state.last_correct = correct
                    st.session_state.last_answer = article
                    st.session_state.answered = True
                    st.session_state.total += 1

                    if correct:
                        st.session_state.score += 1

                    save_answer(
                        word["word"],
                        word["level"],
                        "Artículos",
                        article,
                        word["article"],
                        correct
                    )

                    st.rerun()

    else:

        if st.session_state.last_correct:

            st.success("✅ ¡Correcto!")

        else:

            st.error(
                f"❌ Incorrecto. "
                f"Es **{word['article']}**."
            )

        st.write(
            f"**{word['article']} {word['word']}**"
        )

        if word["example_de"]:

            st.info(
                f"📝 {word['example_de']}"
            )

        if st.button("➡️ Siguiente"):

            reset_question(article_words)

            st.rerun()


# ============================================================
# MÓDULO 2 — VOCABULARIO
# ============================================================

elif module == "Vocabulario":

    if filtered.empty:

        st.warning(
            "No hay vocabulario disponible."
        )

        st.stop()

    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word["word"]
        not in filtered["word"].values
    ):

        reset_question(filtered)

    word = st.session_state.current_word

    st.subheader("📚 Vocabulario")

    direction = st.radio(
        "Dirección",
        [
            "Alemán → Español",
            "Español → Alemán"
        ],
        horizontal=True
    )

    if direction == "Alemán → Español":

        question = word["word"]

        expected = word["translation"]

    else:

        question = word["translation"]

        expected = word["word"]

    st.markdown(
        f'<div class="question">{question}</div>',
        unsafe_allow_html=True
    )

    if not st.session_state.answered:

        answer = st.text_input(
            "Tu respuesta",
            value=st.session_state.answer_text,
            key="vocab_input"
        )

        st.session_state.answer_text = answer

        german_keyboard("answer_text")

        if st.button("Comprobar"):

            correct = (
                normalize(answer)
                == normalize(expected)
            )

            st.session_state.last_correct = correct
            st.session_state.last_answer = answer
            st.session_state.answered = True
            st.session_state.total += 1

            if correct:
                st.session_state.score += 1

            save_answer(
                word["word"],
                word["level"],
                "Vocabulario",
                answer,
                expected,
                correct
            )

            st.rerun()

    else:

        if st.session_state.last_correct:

            st.success("✅ ¡Correcto!")

        else:

            st.error(
                f"❌ Incorrecto. "
                f"Respuesta: **{expected}**"
            )

        if word["example_de"]:

            st.info(
                f"📝 {word['example_de']}"
            )

        if st.button("➡️ Siguiente"):

            reset_question(filtered)

            st.rerun()


# ============================================================
# MÓDULO 3 — PLURALES
# ============================================================

elif module == "Plurales":

    invalid_plural = [
        "",
        "—",
        "–",
        "-",
        "none",
        "nan"
    ]

    plural_words = filtered[
        (
            filtered["part_of_speech"]
            .str.lower()
            .str.strip()
            == "noun"
        )
        &
        (
            filtered["article"]
            .isin(["der", "die", "das"])
        )
        &
        (
            ~filtered["plural"]
            .str.lower()
            .str.strip()
            .isin(invalid_plural)
        )
    ].copy()

    if plural_words.empty:

        st.warning(
            "No hay sustantivos con plural disponible."
        )

        st.stop()

    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word["word"]
        not in plural_words["word"].values
    ):

        reset_question(plural_words)

    word = st.session_state.current_word

    st.subheader("🔢 Escribe el plural")

    st.markdown(
        f'<div class="question">'
        f'{word["article"]} {word["word"]}'
        f'</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        f'<div class="translation">'
        f'🇪🇸 {word["translation"]}'
        f'</div>',
        unsafe_allow_html=True
    )

    if not st.session_state.answered:

        answer = st.text_input(
            "Plural",
            value=st.session_state.answer_text,
            key="plural_input"
        )

        st.session_state.answer_text = answer

        german_keyboard("answer_text")

        if st.button("Comprobar"):

            expected = word["plural"]

            correct = (
                normalize(answer)
                == normalize(expected)
            )

            st.session_state.last_correct = correct
            st.session_state.last_answer = answer
            st.session_state.answered = True
            st.session_state.total += 1

            if correct:
                st.session_state.score += 1

            save_answer(
                word["word"],
                word["level"],
                "Plurales",
                answer,
                expected,
                correct
            )

            st.rerun()

    else:

        if st.session_state.last_correct:

            st.success("✅ ¡Correcto!")

        else:

            st.error("❌ Incorrecto.")

        st.write(
            f"El plural correcto es: "
            f"**die {word['plural']}**"
        )

        if word["example_de"]:

            st.info(
                f"📝 {word['example_de']}"
            )

        if st.button("➡️ Siguiente"):

            reset_question(plural_words)

            st.rerun()


# ============================================================
# MÓDULO 4 — PRÄTERITUM + PARTIZIP II
# ============================================================

elif module == "Präteritum":

    verbs = filtered[
        (
            filtered["part_of_speech"]
            .str.lower()
            .str.strip()
            == "verb"
        )
        &
        (
            filtered["preteritum"].str.strip() != ""
        )
        &
        (
            filtered["partizip_II"].str.strip() != ""
        )
    ].copy()

    if verbs.empty:

        st.warning(
            "No hay verbos con información de pasado."
        )

        st.stop()

    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word["word"]
        not in verbs["word"].values
    ):

        reset_question(verbs)

    word = st.session_state.current_word

    st.subheader(
        "⏳ Präteritum + Partizip II"
    )

    st.markdown(
        f'<div class="question">{word["word"]}</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        f'<div class="translation">'
        f'🇪🇸 {word["translation"]}'
        f'</div>',
        unsafe_allow_html=True
    )

    if not st.session_state.answered:

        st.write(
            "Escribe las dos formas:"
        )

        st.write(
            "Präteritum"
        )

        preteritum = st.text_input(
            "Präteritum",
            value=st.session_state.past_answer_text,
            key="preteritum_input"
        )

        st.session_state.past_answer_text = preteritum

        st.write(
            "Partizip II"
        )

        particip = st.text_input(
            "Partizip II",
            key="particip_input"
        )

        german_keyboard("past_answer_text")

        if st.button("Comprobar"):

            correct_preteritum = (
                normalize(preteritum)
                ==
                normalize(word["preteritum"])
            )

            correct_particip = (
                normalize(particip)
                ==
                normalize(word["partizip_II"])
            )

            correct = (
                correct_preteritum
                and
                correct_particip
            )

            st.session_state.last_correct = correct

            st.session_state.last_answer = (
                f"{preteritum} / {particip}"
            )

            st.session_state.answered = True
            st.session_state.total += 1

            if correct:
                st.session_state.score += 1

            save_answer(
                word["word"],
                word["level"],
                "Präteritum",
                f"{preteritum} / {particip}",
                f"{word['preteritum']} / {word['partizip_II']}",
                correct
            )

            st.rerun()

    else:

        if st.session_state.last_correct:

            st.success("✅ ¡Las dos formas son correctas!")

        else:

            st.error("❌ Hay una forma incorrecta.")

            st.write(
                f"Präteritum: "
                f"**{word['preteritum']}**"
            )

            st.write(
                f"Partizip II: "
                f"**{word['partizip_II']}**"
            )

        if word["example_de"]:

            st.info(
                f"📝 {word['example_de']}"
            )

        if st.button("➡️ Siguiente"):

            reset_question(verbs)

            st.rerun()


# ============================================================
# MÓDULO 5 — NOMINATIV / AKKUSATIV / DATIV
# ============================================================

elif module == "Casos":

    nouns = filtered[
        (
            filtered["part_of_speech"]
            .str.lower()
            .str.strip()
            == "noun"
        )
        &
        (
            filtered["article"]
            .isin(["der", "die", "das"])
        )
    ].copy()

    if nouns.empty:

        st.warning(
            "No hay sustantivos disponibles."
        )

        st.stop()

    # --------------------------------------------------------
    # Generar frases
    # --------------------------------------------------------

    case_examples = {

        "Mann": [
            ("Nominativ", "der", "___ Mann ist nett.",
             "El hombre es amable.",
             "Sujeto de la oración."),

            ("Akkusativ", "den", "Ich sehe ___ Mann.",
             "Veo al hombre.",
             "Objeto directo."),

            ("Dativ", "dem", "Ich helfe ___ Mann.",
             "Ayudo al hombre.",
             "El verbo 'helfen' utiliza Dativ.")
        ],

        "Frau": [
            ("Nominativ", "die", "___ Frau arbeitet hier.",
             "La mujer trabaja aquí.",
             "Sujeto de la oración."),

            ("Akkusativ", "die", "Ich kenne ___ Frau.",
             "Conozco a la mujer.",
             "Objeto directo."),

            ("Dativ", "der", "Ich spreche mit ___ Frau.",
             "Hablo con la mujer.",
             "La preposición 'mit' utiliza Dativ.")
        ],

        "Kind": [
            ("Nominativ", "das", "___ Kind spielt.",
             "El niño juega.",
             "Sujeto de la oración."),

            ("Akkusativ", "das", "Ich sehe ___ Kind.",
             "Veo al niño.",
             "Objeto directo."),

            ("Dativ", "dem", "Ich helfe ___ Kind.",
             "Ayudo al niño.",
             "El verbo 'helfen' utiliza Dativ.")
        ],

        "Hund": [
            ("Nominativ", "der", "___ Hund ist klein.",
             "El perro es pequeño.",
             "Sujeto de la oración."),

            ("Akkusativ", "den", "Ich sehe ___ Hund.",
             "Veo al perro.",
             "Objeto directo."),

            ("Dativ", "dem", "Ich gebe ___ Hund Wasser.",
             "Le doy agua al perro.",
             "Objeto indirecto.")
        ],

        "Katze": [
            ("Nominativ", "die", "___ Katze schläft.",
             "El gato duerme.",
             "Sujeto de la oración."),

            ("Akkusativ", "die", "Ich sehe ___ Katze.",
             "Veo al gato.",
             "Objeto directo."),

            ("Dativ", "der", "Ich gebe ___ Katze Wasser.",
             "Le doy agua al gato.",
             "Objeto indirecto.")
        ],

        "Buch": [
            ("Nominativ", "das", "___ Buch ist interessant.",
             "El libro es interesante.",
             "Sujeto de la oración."),

            ("Akkusativ", "das", "Ich lese ___ Buch.",
             "Leo el libro.",
             "Objeto directo."),

            ("Dativ", "dem", "Ich vertraue ___ Buch nicht.",
             "No confío en el libro.",
             "El verbo 'vertrauen' utiliza Dativ.")
        ]
    }

    # --------------------------------------------------------
    # Construir ejercicios automáticamente
    # --------------------------------------------------------

    possible_cases = []

    for _, noun in nouns.iterrows():

        word = noun["word"]
        article = noun["article"]

        if word in case_examples:

            for item in case_examples[word]:

                possible_cases.append(
                    {
                        "word": word,
                        "article": article,
                        "translation": noun["translation"],
                        "level": noun["level"],
                        "case": item[0],
                        "answer": item[1],
                        "sentence": item[2],
                        "translation_sentence": item[3],
                        "explanation": item[4]
                    }
                )

        else:

            # Para el resto de sustantivos:
            if article == "der":

                cases = [
                    (
                        "Nominativ",
                        "der",
                        f"___ {word} ist hier.",
                        f"{word} está aquí.",
                        "Sujeto."
                    ),
                    (
                        "Akkusativ",
                        "den",
                        f"Ich sehe ___ {word}.",
                        f"Veo {noun['translation']}.",
                        "Objeto directo."
                    ),
                    (
                        "Dativ",
                        "dem",
                        f"Ich spreche mit ___ {word}.",
                        f"Hablo con {noun['translation']}.",
                        "La preposición 'mit' utiliza Dativ."
                    )
                ]

            elif article == "die":

                cases = [
                    (
                        "Nominativ",
                        "die",
                        f"___ {word} ist hier.",
                        f"{noun['translation'].capitalize()} está aquí.",
                        "Sujeto."
                    ),
                    (
                        "Akkusativ",
                        "die",
                        f"Ich sehe ___ {word}.",
                        f"Veo {noun['translation']}.",
                        "Objeto directo."
                    ),
                    (
                        "Dativ",
                        "der",
                        f"Ich spreche mit ___ {word}.",
                        f"Hablo con {noun['translation']}.",
                        "La preposición 'mit' utiliza Dativ."
                    )
                ]

            else:

                cases = [
                    (
                        "Nominativ",
                        "das",
                        f"___ {word} ist hier.",
                        f"{noun['translation'].capitalize()} está aquí.",
                        "Sujeto."
                    ),
                    (
                        "Akkusativ",
                        "das",
                        f"Ich sehe ___ {word}.",
                        f"Veo {noun['translation']}.",
                        "Objeto directo."
                    ),
                    (
                        "Dativ",
                        "dem",
                        f"Ich spreche mit ___ {word}.",
                        f"Hablo con {noun['translation']}.",
                        "La preposición 'mit' utiliza Dativ."
                    )
                ]

            for item in cases:

                possible_cases.append(
                    {
                        "word": word,
                        "article": article,
                        "translation": noun["translation"],
                        "level": noun["level"],
                        "case": item[0],
                        "answer": item[1],
                        "sentence": item[2],
                        "translation_sentence": item[3],
                        "explanation": item[4]
                    }
                )

    cases_df = pd.DataFrame(
        possible_cases
    )

    if cases_df.empty:

        st.warning(
            "No hay ejercicios de casos."
        )

        st.stop()

    # --------------------------------------------------------
    # Nueva pregunta
    # --------------------------------------------------------

    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word.get("sentence")
        not in cases_df["sentence"].values
    ):

        reset_question(cases_df)

    question = st.session_state.current_word

    st.subheader(
        "🇩🇪 Nominativ · Akkusativ · Dativ"
    )

    st.caption(
        "Modo mixto — sin pistas"
    )

    st.markdown(
        f'<div class="question">'
        f'{question["sentence"]}'
        f'</div>',
        unsafe_allow_html=True
    )

    if not st.session_state.answered:

        answer = st.text_input(
            "Completa la frase",
            value=st.session_state.case_answer_text,
            key="case_input"
        )

        st.session_state.case_answer_text = answer

        german_keyboard("case_answer_text")

        if st.button("Comprobar"):

            expected = question["answer"]

            correct = (
                normalize(answer)
                == normalize(expected)
            )

            st.session_state.last_correct = correct
            st.session_state.last_answer = answer
            st.session_state.answered = True
            st.session_state.total += 1

            if correct:
                st.session_state.score += 1

            save_answer(
                question["word"],
                question["level"],
                "Casos",
                answer,
                expected,
                correct
            )

            st.rerun()

    else:

        if st.session_state.last_correct:

            st.success("✅ ¡Correcto!")

        else:

            st.error("❌ Incorrecto.")

            st.write(
                f"Respuesta correcta: "
                f"**{question['answer']}**"
            )

        # Mostrar la frase completa
        full_sentence = question["sentence"].replace(
            "___",
            question["answer"]
        )

        st.markdown(
            f"""
            <div class="case-box">
            <strong>{full_sentence}</strong>
            <br><br>
            🇪🇸 {question["translation_sentence"]}
            </div>
            """,
            unsafe_allow_html=True
        )

        st.write(
            f"**Caso:** {question['case']}"
        )

        st.caption(
            f"💡 {question['explanation']}"
        )

        if st.button("➡️ Siguiente"):

            reset_question(cases_df)

            st.rerun()


# ============================================================
# ESTADÍSTICAS
# ============================================================

st.sidebar.divider()

st.sidebar.subheader("📊 Sesión")

if st.session_state.total > 0:

    accuracy = (
        st.session_state.score
        /
        st.session_state.total
        *
        100
    )

else:

    accuracy = 0


st.sidebar.metric(
    "Aciertos",
    f"{st.session_state.score}/{st.session_state.total}"
)

st.sidebar.metric(
    "Precisión",
    f"{accuracy:.0f}%"
)


# ============================================================
# HISTORIAL
# ============================================================

if st.sidebar.button(
    "🗑️ Reiniciar sesión"
):

    st.session_state.score = 0
    st.session_state.total = 0
    st.session_state.current_word = None
    st.session_state.answered = False

    st.rerun()


# ============================================================
# ESTADÍSTICAS DE BASE DE DATOS
# ============================================================

with st.expander("📈 Estadísticas generales"):

    conn = sqlite3.connect(DB_FILE)

    history = pd.read_sql_query(
        """
        SELECT
            module,
            COUNT(*) AS preguntas,
            SUM(correct) AS aciertos
        FROM answers
        GROUP BY module
        ORDER BY module
        """,
        conn
    )

    conn.close()

    if history.empty:

        st.info(
            "Todavía no hay estadísticas."
        )

    else:

        history["precisión"] = (
            history["aciertos"]
            /
            history["preguntas"]
            *
            100
        ).round(1)

        st.dataframe(
            history,
            use_container_width=True,
            hide_index=True
        )