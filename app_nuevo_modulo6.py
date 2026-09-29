import streamlit as st
import pandas as pd
import sqlite3
import random
import re
from pathlib import Path
from datetime import datetime

# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Deutsch Lernen",
    page_icon="🇩🇪",
    layout="centered",
)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "vocabulary_A1_B1_plus_400.xlsx"
DB_FILE = BASE_DIR / "progress.db"

MODULES = [
    "Artículos",
    "Vocabulario",
    "Plurales",
    "Partizip II",
    "Casos",
    "Declinaciones",
]

LEVELS = ["Todos", "A1", "A2", "B1"]

GERMAN_CHARS = ["ä", "ö", "ü", "Ä", "Ö", "Ü", "ß"]


# ============================================================
# ESTILOS
# ============================================================

st.markdown(
    """
    <style>
    .question {
        font-size: 2.2rem;
        font-weight: 700;
        text-align: center;
        margin: 1rem 0;
    }

    .translation {
        font-size: 1.2rem;
        text-align: center;
        margin-bottom: 1.5rem;
    }

    .case_sentence {
        font-size: 1.35rem;
        line-height: 1.8;
        text-align: center;
        margin: 1rem 0;
    }

    .small_info {
        text-align: center;
        opacity: 0.8;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# NORMALIZACIÓN
# ============================================================

def normalize(value):
    if value is None:
        return ""

    text = str(value).strip().lower()

    replacements = {
        "ä": "ä",
        "ö": "ö",
        "ü": "ü",
        "ß": "ß",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\s+", " ", text)

    return text


def clean_text(value):
    if pd.isna(value):
        return ""

    return str(value).strip()


# ============================================================
# CARGA DEL EXCEL
# ============================================================

@st.cache_data
def load_vocabulary():
    if not DATA_FILE.exists():
        st.error(
            "No se encontró el archivo de vocabulario.\n\n"
            f"Ruta esperada:\n{DATA_FILE}"
        )
        st.stop()

    df = pd.read_excel(
        DATA_FILE,
        sheet_name="Vocabulary",
        engine="openpyxl",
    )

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
        "partizip_II",
    ]

    for column in required_columns:
        if column not in df.columns:
            df[column] = ""

    for column in required_columns:
        if column in df.columns:
            df[column] = df[column].fillna("").astype(str)

    return df


@st.cache_data
def load_cases_from_excel():
    """
    Carga la hoja Cases si existe.
    El módulo de Casos utiliza además un generador de plantillas,
    por lo que no depende exclusivamente de esta hoja.
    """
    try:
        cases = pd.read_excel(
            DATA_FILE,
            sheet_name="Cases",
            engine="openpyxl",
        )
        return cases
    except Exception:
        return pd.DataFrame()


df = load_vocabulary()
cases_excel = load_cases_from_excel()


# ============================================================
# SQLITE — HISTORIAL Y PROGRESO
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS answer_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            level TEXT,
            module TEXT,
            user_answer TEXT,
            correct_answer TEXT,
            correct INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS question_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            question_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_question_history
        ON question_history(module, question_id, created_at)
        """
    )

    conn.commit()
    conn.close()


init_db()


def save_answer(
    word,
    level,
    module,
    user_answer,
    correct_answer,
    correct,
):
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT INTO answer_history
        (
            word,
            level,
            module,
            user_answer,
            correct_answer,
            correct
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(word),
            str(level),
            str(module),
            str(user_answer),
            str(correct_answer),
            int(bool(correct)),
        ),
    )

    conn.commit()
    conn.close()


def register_question(module, question_id):
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT INTO question_history
        (module, question_id)
        VALUES (?, ?)
        """,
        (module, str(question_id)),
    )

    conn.commit()
    conn.close()


def get_recent_question_ids(module, limit=40):
    conn = sqlite3.connect(DB_FILE)

    rows = conn.execute(
        """
        SELECT question_id
        FROM question_history
        WHERE module = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (module, limit),
    ).fetchall()

    conn.close()

    return {str(row[0]) for row in rows}


def choose_from_dataframe(
    available,
    module,
    id_column="id",
    recent_limit=40,
):
    """
    Selecciona una pregunta evitando las últimas N preguntas
    usadas en ese módulo.
    """
    if available.empty:
        return None

    available = available.copy()

    if id_column not in available.columns:
        available["_question_id"] = available.index.astype(str)
        id_column = "_question_id"

    available[id_column] = (
        available[id_column]
        .fillna("")
        .astype(str)
    )

    recent_ids = get_recent_question_ids(
        module,
        limit=recent_limit,
    )

    candidates = available[
        ~available[id_column].isin(recent_ids)
    ]

    # Si ya se utilizaron todas, empezamos a reutilizar.
    if candidates.empty:
        candidates = available

    selected = candidates.sample(
        n=1,
        random_state=random.randint(1, 10_000_000),
    ).iloc[0]

    question_id = selected[id_column]

    register_question(
        module,
        question_id,
    )

    return selected.to_dict()


# ============================================================
# ESTADO DE SESIÓN
# ============================================================

if "module" not in st.session_state:
    st.session_state.module = "Artículos"

if "previous_module" not in st.session_state:
    st.session_state.previous_module = "Artículos"

if "level" not in st.session_state:
    st.session_state.level = "Todos"

if "questions" not in st.session_state:
    st.session_state.questions = {
        module: None
        for module in MODULES
    }

if "answered" not in st.session_state:
    st.session_state.answered = {
        module: False
        for module in MODULES
    }

if "last_correct" not in st.session_state:
    st.session_state.last_correct = {
        module: None
        for module in MODULES
    }

if "last_answer" not in st.session_state:
    st.session_state.last_answer = {
        module: ""
        for module in MODULES
    }

if "score" not in st.session_state:
    st.session_state.score = 0

if "total" not in st.session_state:
    st.session_state.total = 0

if "answer_text" not in st.session_state:
    st.session_state.answer_text = ""

if "plural_input" not in st.session_state:
    st.session_state.plural_input = ""

if "particip_input" not in st.session_state:
    st.session_state.particip_input = ""

if "vocab_input" not in st.session_state:
    st.session_state.vocab_input = ""

if "case_input" not in st.session_state:
    st.session_state.case_input = ""



# ============================================================
# FUNCIONES DE ESTADO
# ============================================================

def reset_module(module, available=None):
    st.session_state.questions[module] = None
    st.session_state.answered[module] = False
    st.session_state.last_correct[module] = None
    st.session_state.last_answer[module] = ""

    if module == "Vocabulario":
        st.session_state.vocab_input = ""

    elif module == "Plurales":
        st.session_state.plural_input = ""

    elif module == "Partizip II":
        st.session_state.particip_input = ""

    elif module == "Casos":
        st.session_state.case_input = ""


    if available is not None and not available.empty:
        st.session_state.questions[module] = choose_from_dataframe(
            available,
            module,
        )


def german_keyboard(state_key):
    """
    Teclado alemán reutilizable.
    """
    cols = st.columns(7)

    for col, char in zip(cols, GERMAN_CHARS):
        if col.button(
            char,
            key=f"{state_key}_keyboard_{char}",
        ):
            current = st.session_state.get(
                state_key,
                "",
            )

            st.session_state[state_key] = (
                current + char
            )

            st.rerun()


def mark_answer(
    module,
    word,
    level,
    user_answer,
    correct_answer,
    correct,
):
    st.session_state.last_correct[module] = correct
    st.session_state.last_answer[module] = user_answer
    st.session_state.answered[module] = True

    st.session_state.total += 1

    if correct:
        st.session_state.score += 1

    save_answer(
        word,
        level,
        module,
        user_answer,
        correct_answer,
        correct,
    )


def next_question(module, available):
    st.session_state.questions[module] = choose_from_dataframe(
        available,
        module,
    )

    st.session_state.answered[module] = False
    st.session_state.last_correct[module] = None
    st.session_state.last_answer[module] = ""

    if module == "Vocabulario":
        st.session_state.vocab_input = ""

    elif module == "Plurales":
        st.session_state.plural_input = ""

    elif module == "Partizip II":
        st.session_state.particip_input = ""

    elif module == "Casos":
        st.session_state.case_input = ""


    st.rerun()


# ============================================================
# FILTRO DE NIVEL
# ============================================================

st.sidebar.title("🇩🇪 Deutsch Lernen")

selected_level = st.sidebar.selectbox(
    "Nivel",
    LEVELS,
    index=LEVELS.index(st.session_state.level),
)

if selected_level != st.session_state.level:
    st.session_state.level = selected_level

    # Al cambiar de nivel, cada módulo obtiene su siguiente
    # pregunta compatible.
    for module_name in MODULES:
        st.session_state.questions[module_name] = None
        st.session_state.answered[module_name] = False


filtered = df.copy()

if st.session_state.level != "Todos":
    filtered = filtered[
        filtered["level"].str.upper().str.strip()
        == st.session_state.level
    ].copy()


# ============================================================
# MENÚ
# ============================================================

module = st.sidebar.selectbox(
    "Módulo",
    MODULES,
    index=MODULES.index(st.session_state.module),
)

# Si el usuario cambia de módulo, NO se arrastra la palabra
# del módulo anterior.
if module != st.session_state.previous_module:
    st.session_state.module = module
    st.session_state.previous_module = module

    if st.session_state.questions[module] is None:
        st.session_state.answered[module] = False


# ============================================================
# ESTADÍSTICAS
# ============================================================

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Progreso")

if st.session_state.total > 0:
    percentage = (
        st.session_state.score
        / st.session_state.total
        * 100
    )
else:
    percentage = 0

st.sidebar.write(
    f"Correctas: **{st.session_state.score}**"
)

st.sidebar.write(
    f"Respondidas: **{st.session_state.total}**"
)

st.sidebar.write(
    f"Precisión: **{percentage:.1f}%**"
)

if st.sidebar.button("🔄 Reiniciar puntuación"):
    st.session_state.score = 0
    st.session_state.total = 0
    st.rerun()


# ============================================================
# TÍTULO
# ============================================================

st.title("🇩🇪 Deutsch Lernen")

st.caption(
    f"Nivel: {st.session_state.level} · "
    f"Módulo: {module}"
)


# ============================================================
# MÓDULO 1 — ARTÍCULOS
# ============================================================

if module == "Artículos":

    articles = filtered[
        filtered["article"]
        .str.lower()
        .str.strip()
        .isin(["der", "die", "das"])
    ].copy()

    if articles.empty:
        st.warning(
            "No hay palabras con artículos para este nivel."
        )
        st.stop()

    if st.session_state.questions[module] is None:
        st.session_state.questions[module] = choose_from_dataframe(
            articles,
            module,
        )

    word = st.session_state.questions[module]

    st.subheader("📝 ¿Qué artículo lleva?")

    st.markdown(
        f'<div class="question">{word["word"]}</div>',
        unsafe_allow_html=True,
    )

    if word["translation"]:
        st.markdown(
            f'<div class="translation">'
            f'🇪🇸 {word["translation"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if not st.session_state.answered[module]:

        cols = st.columns(3)

        for col, article in zip(
            cols,
            ["der", "die", "das"],
        ):

            if col.button(
                article,
                key=f"article_{article}_{word['id']}",
                use_container_width=True,
            ):

                correct = (
                    normalize(article)
                    == normalize(word["article"])
                )

                mark_answer(
                    module,
                    word["word"],
                    word["level"],
                    article,
                    word["article"],
                    correct,
                )

                st.rerun()

    else:

        if st.session_state.last_correct[module]:
            st.success("✅ ¡Correcto!")
        else:
            st.error(
                f"❌ Incorrecto. "
                f"Es **{word['article']} {word['word']}**."
            )

        if word["example_de"]:
            st.info(
                f"📝 {word['example_de']}"
            )

        if st.button(
            "➡️ Siguiente",
            key=f"next_articles_{word['id']}",
        ):
            next_question(
                module,
                articles,
            )


# ============================================================
# MÓDULO 2 — VOCABULARIO
# ============================================================

elif module == "Vocabulario":

    vocab = filtered[
        filtered["word"].str.strip() != ""
    ].copy()

    if vocab.empty:
        st.warning("No hay vocabulario disponible.")
        st.stop()

    if st.session_state.questions[module] is None:
        st.session_state.questions[module] = choose_from_dataframe(
            vocab,
            module,
        )

    word = st.session_state.questions[module]

    st.subheader("🗣️ Vocabulario")

    # 50/50 alemán -> español o español -> alemán
    if "direction" not in word:
        word["direction"] = random.choice(
            ["de_to_es", "es_to_de"]
        )

    if word["direction"] == "de_to_es":

        st.write("Traduce al español:")

        st.markdown(
            f'<div class="question">{word["word"]}</div>',
            unsafe_allow_html=True,
        )

        correct_answer = word["translation"]

    else:

        st.write("Traduce al alemán:")

        st.markdown(
            f'<div class="question">{word["translation"]}</div>',
            unsafe_allow_html=True,
        )

        correct_answer = word["word"]

    if not st.session_state.answered[module]:

        answer = st.text_input(
            "Tu respuesta",
            key="vocab_input",
        )

        german_keyboard("vocab_input")

        if st.button(
            "Comprobar",
            key=f"check_vocab_{word['id']}",
        ):

            correct = (
                normalize(answer)
                == normalize(correct_answer)
            )

            mark_answer(
                module,
                word["word"],
                word["level"],
                answer,
                correct_answer,
                correct,
            )

            st.rerun()

    else:

        if st.session_state.last_correct[module]:
            st.success("✅ ¡Correcto!")
        else:
            st.error(
                f"❌ La respuesta correcta es: "
                f"**{correct_answer}**"
            )

        if word["example_de"]:
            st.info(
                f"📝 {word['example_de']}"
            )

        if word["example_es"]:
            st.caption(
                f"🇪🇸 {word['example_es']}"
            )

        if st.button(
            "➡️ Siguiente",
            key=f"next_vocab_{word['id']}",
        ):
            next_question(
                module,
                vocab,
            )


# ============================================================
# MÓDULO 3 — PLURALES
# ============================================================

elif module == "Plurales":

    plural_values = (
        filtered["plural"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    articles_values = (
        filtered["article"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    pos_values = (
        filtered["part_of_speech"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    invalid_plural = {
        "",
        "-",
        "—",
        "–",
        "none",
        "nan",
        "null",
    }

    plurals = filtered[
        pos_values.eq("noun")
        &
        articles_values.isin(
            ["der", "die", "das"]
        )
        &
        ~plural_values.isin(invalid_plural)
    ].copy()

    if plurals.empty:
        st.warning(
            "No hay sustantivos con plurales válidos."
        )
        st.stop()

    if st.session_state.questions[module] is None:
        st.session_state.questions[module] = choose_from_dataframe(
            plurals,
            module,
        )

    word = st.session_state.questions[module]

    st.subheader("🔤 Plurales")

    st.markdown(
        f'<div class="question">'
        f'{word["article"]} {word["word"]}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if word["translation"]:
        st.markdown(
            f'<div class="translation">'
            f'🇪🇸 {word["translation"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if not st.session_state.answered[module]:

        plural = st.text_input(
            "Escribe el plural:",
            key="plural_input",
        )

        german_keyboard("plural_input")

        if st.button(
            "Comprobar",
            key=f"check_plural_{word['id']}",
        ):

            correct_answer = word["plural"]

            correct = (
                normalize(plural)
                == normalize(correct_answer)
            )

            mark_answer(
                module,
                word["word"],
                word["level"],
                plural,
                correct_answer,
                correct,
            )

            st.rerun()

    else:

        if st.session_state.last_correct[module]:
            st.success("✅ ¡Correcto!")
        else:
            st.error(
                f"❌ El plural correcto es: "
                f"**{word['plural']}**"
            )

        if word["example_de"]:
            st.info(
                f"📝 {word['example_de']}"
            )

        if st.button(
            "➡️ Siguiente",
            key=f"next_plural_{word['id']}",
        ):
            next_question(
                module,
                plurals,
            )


# ============================================================
# MÓDULO 4 — PARTIZIP II
# ============================================================

elif module == "Partizip II":

    pos_values = (
        filtered["part_of_speech"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    particip_values = (
        filtered["partizip_II"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    verbs = filtered[
        pos_values.eq("verb")
        &
        particip_values.ne("")
        &
        particip_values.str.lower().ne("nan")
    ].copy()

    if verbs.empty:
        st.warning(
            "No hay verbos con información de Partizip II."
        )
        st.stop()

    if st.session_state.questions[module] is None:
        st.session_state.questions[module] = choose_from_dataframe(
            verbs,
            module,
        )

    word = st.session_state.questions[module]

    st.subheader("🇩🇪 Partizip II")

    st.markdown(
        f'<div class="question">{word["word"]}</div>',
        unsafe_allow_html=True,
    )

    if word["translation"]:
        st.markdown(
            f'<div class="translation">'
            f'🇪🇸 {word["translation"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if not st.session_state.answered[module]:

        particip = st.text_input(
            "Escribe el Partizip II:",
            key="particip_input",
        )

        german_keyboard("particip_input")

        if st.button(
            "Comprobar",
            key=f"check_particip_{word['id']}",
        ):

            correct_answer = word["partizip_II"]

            correct = (
                normalize(particip)
                == normalize(correct_answer)
            )

            mark_answer(
                module,
                word["word"],
                word["level"],
                particip,
                correct_answer,
                correct,
            )

            st.rerun()

    else:

        if st.session_state.last_correct[module]:

            st.success("✅ ¡Correcto!")

        else:

            st.error(
                f"❌ Incorrecto. "
                f"El Partizip II es: "
                f"**{word['partizip_II']}**"
            )

        if word["example_de"]:
            st.info(
                f"📝 {word['example_de']}"
            )

        if st.button(
            "➡️ Siguiente",
            key=f"next_particip_{word['id']}",
        ):
            next_question(
                module,
                verbs,
            )


# ============================================================
# MÓDULO 5 — CASOS
# ============================================================

elif module == "Casos":

    # --------------------------------------------------------
    # Banco de sustantivos
    # --------------------------------------------------------

    nouns = filtered[
        filtered["part_of_speech"]
        .fillna("")
        .str.lower()
        .str.strip()
        .eq("noun")
    ].copy()

    nouns = nouns[
        nouns["article"]
        .fillna("")
        .str.lower()
        .str.strip()
        .isin(["der", "die", "das"])
    ].copy()

    if nouns.empty:
        st.warning(
            "No hay sustantivos adecuados para generar ejercicios."
        )
        st.stop()

    # --------------------------------------------------------
    # Generador de casos
    # --------------------------------------------------------

    CASE_TEMPLATES = {
        "Nominativ": [
            {
                "pattern": "___ {noun} arbeitet heute.",
                "case": "Nominativ",
                "reason": "El sustantivo es el sujeto de la oración.",
            },
            {
                "pattern": "___ {noun} ist sehr groß.",
                "case": "Nominativ",
                "reason": "El sustantivo es el sujeto de la oración.",
            },
            {
                "pattern": "___ {noun} steht vor dem Haus.",
                "case": "Nominativ",
                "reason": "El sustantivo es el sujeto de la oración.",
            },
            {
                "pattern": "___ {noun} kommt heute.",
                "case": "Nominativ",
                "reason": "El sustantivo realiza la acción.",
            },
            {
                "pattern": "___ {noun} ist neu.",
                "case": "Nominativ",
                "reason": "El sustantivo es el sujeto.",
            },
        ],

        "Akkusativ": [
            {
                "pattern": "Ich sehe ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo recibe directamente la acción de ver.",
            },
            {
                "pattern": "Ich kaufe ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo es el objeto directo de kaufen.",
            },
            {
                "pattern": "Ich brauche ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo funciona como objeto directo.",
            },
            {
                "pattern": "Ich suche ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo es el objeto directo de suchen.",
            },
            {
                "pattern": "Ich habe ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo funciona como objeto directo.",
            },
            {
                "pattern": "Wir besuchen ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo es el objeto directo de besuchen.",
            },
            {
                "pattern": "Er nimmt ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo es el objeto directo de nehmen.",
            },
            {
                "pattern": "Sie öffnet ___ {noun}.",
                "case": "Akkusativ",
                "reason": "El sustantivo es el objeto directo de öffnen.",
            },
        ],

        "Dativ": [
            {
                "pattern": "Ich helfe ___ {noun}.",
                "case": "Dativ",
                "reason": "El verbo helfen rige Dativ.",
            },
            {
                "pattern": "Ich danke ___ {noun}.",
                "case": "Dativ",
                "reason": "El verbo danken rige Dativ.",
            },
            {
                "pattern": "Ich folge ___ {noun}.",
                "case": "Dativ",
                "reason": "El verbo folgen rige Dativ.",
            },
            {
                "pattern": "Ich vertraue ___ {noun}.",
                "case": "Dativ",
                "reason": "El verbo vertrauen rige Dativ.",
            },
            {
                "pattern": "Ich spreche mit ___ {noun}.",
                "case": "Dativ",
                "reason": "La preposición mit rige Dativ.",
            },
            {
                "pattern": "Ich fahre mit ___ {noun}.",
                "case": "Dativ",
                "reason": "La preposición mit rige Dativ.",
            },
            {
                "pattern": "Ich bin bei ___ {noun}.",
                "case": "Dativ",
                "reason": "La preposición bei rige Dativ.",
            },
        ],
    }

    def article_for_case(base_article, case):
        """
        Solo transformamos artículos definidos.
        Nominativ: der/die/das
        Akkusativ: den/die/das
        Dativ: dem/der/dem
        """
        article = normalize(base_article)

        mapping = {
            "Nominativ": {
                "der": "der",
                "die": "die",
                "das": "das",
            },
            "Akkusativ": {
                "der": "den",
                "die": "die",
                "das": "das",
            },
            "Dativ": {
                "der": "dem",
                "die": "der",
                "das": "dem",
            },
        }

        return mapping[case][article]

    def create_case_question():
        """
        Crea una pregunta con:
        - caso aleatorio
        - plantilla aleatoria
        - sustantivo compatible
        - identificador único para anti-repetición
        """

        cases = [
            "Nominativ",
            "Akkusativ",
            "Dativ",
        ]

        # Intentamos varias veces para no repetir combinación.
        for _ in range(30):

            selected_case = random.choice(cases)

            template = random.choice(
                CASE_TEMPLATES[selected_case]
            )

            noun_row = nouns.sample(
                n=1
            ).iloc[0].to_dict()

            article = article_for_case(
                noun_row["article"],
                selected_case,
            )

            sentence = template["pattern"].format(
                noun=noun_row["word"]
            )

            question_id = (
                f"{selected_case}|"
                f"{template['pattern']}|"
                f"{noun_row['id']}"
            )

            recent = get_recent_question_ids(
                "Casos",
                limit=100,
            )

            if question_id not in recent:
                register_question(
                    "Casos",
                    question_id,
                )

                return {
                    "id": question_id,
                    "case": selected_case,
                    "pattern": template["pattern"],
                    "sentence": sentence,
                    "reason": template["reason"],
                    "noun": noun_row["word"],
                    "noun_id": noun_row["id"],
                    "base_article": noun_row["article"],
                    "correct_article": article,
                    "translation": noun_row["translation"],
                }

        # Si excepcionalmente se agotó el banco,
        # permitimos reutilizar una combinación.
        selected_case = random.choice(cases)

        template = random.choice(
            CASE_TEMPLATES[selected_case]
        )

        noun_row = nouns.sample(
            n=1
        ).iloc[0].to_dict()

        article = article_for_case(
            noun_row["article"],
            selected_case,
        )

        question_id = (
            f"{selected_case}|"
            f"{template['pattern']}|"
            f"{noun_row['id']}"
        )

        register_question(
            "Casos",
            question_id,
        )

        return {
            "id": question_id,
            "case": selected_case,
            "pattern": template["pattern"],
            "sentence": template["pattern"].format(
                noun=noun_row["word"]
            ),
            "reason": template["reason"],
            "noun": noun_row["word"],
            "noun_id": noun_row["id"],
            "base_article": noun_row["article"],
            "correct_article": article,
            "translation": noun_row["translation"],
        }

    # --------------------------------------------------------
    # Obtener pregunta
    # --------------------------------------------------------

    if st.session_state.questions[module] is None:
        st.session_state.questions[module] = create_case_question()

    question = st.session_state.questions[module]

    st.subheader("📋 Casos")

    st.caption(
        "Nominativ · Akkusativ · Dativ"
    )

    st.markdown(
        "Completa el artículo. "
        "**No se muestra el caso antes de responder.**"
    )

    # Construimos la frase con un hueco visible.
    sentence_display = question["sentence"].replace(
        "___",
        "_____",
        1,
    )

    st.markdown(
        f'<div class="case_sentence">'
        f'{sentence_display}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if not st.session_state.answered[module]:

        answer = st.text_input(
            "Artículo:",
            key="case_input",
        )

        german_keyboard("case_input")

        if st.button(
            "Comprobar",
            key=f"check_case_{question['id']}",
        ):

            correct = (
                normalize(answer)
                == normalize(
                    question["correct_article"]
                )
            )

            mark_answer(
                module,
                question["noun"],
                st.session_state.level,
                answer,
                question["correct_article"],
                correct,
            )

            st.rerun()

    else:

        # Frase completa
        full_sentence = question["sentence"].replace(
            "___",
            question["correct_article"],
            1,
        )

        if st.session_state.last_correct[module]:

            st.success("✅ ¡Correcto!")

        else:

            st.error(
                f"❌ El artículo correcto es "
                f"**{question['correct_article']}**."
            )

        st.markdown(
            f'<div class="case_sentence">'
            f'{full_sentence}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Explicación después de contestar.
        st.info(
            f"**Caso: {question['case']}**\n\n"
            f"{question['reason']}"
        )

        if question["translation"]:
            st.caption(
                f"🇪🇸 Sustantivo: "
                f"{question['translation']}"
            )

        if st.button(
            "➡️ Siguiente",
            key=f"next_case_{question['id']}",
        ):

            st.session_state.questions[module] = (
                create_case_question()
            )

            st.session_state.answered[module] = False
            st.session_state.last_correct[module] = None
            st.session_state.last_answer[module] = ""
            st.session_state.case_input = ""

            st.rerun()


# ============================================================
# MÓDULO 6 — DECLINACIONES
# ============================================================

elif module == "Declinaciones":

    # --------------------------------------------------------
    # Banco de sustantivos
    # --------------------------------------------------------

    nouns = filtered[
        filtered["part_of_speech"]
        .fillna("")
        .str.lower()
        .str.strip()
        .eq("noun")
    ].copy()

    nouns = nouns[
        nouns["article"]
        .fillna("")
        .str.lower()
        .str.strip()
        .isin(["der", "die", "das"])
    ].copy()

    nouns = nouns[
        nouns["word"]
        .fillna("")
        .str.strip()
        .ne("")
    ].copy()

    if nouns.empty:
        st.warning(
            "No hay sustantivos adecuados para generar ejercicios."
        )
        st.stop()

    # --------------------------------------------------------
    # Adjetivos
    # --------------------------------------------------------
    # Los adjetivos se mantienen separados del Excel para que
    # podamos generar muchas combinaciones sin añadir cientos
    # de filas manualmente.

    ADJECTIVES = [
        "blau",
        "groß",
        "klein",
        "alt",
        "neu",
        "gut",
        "schön",
        "schnell",
        "langsam",
        "teuer",
        "billig",
        "wichtig",
        "interessant",
        "lang",
        "kurz",
        "jung",
        "warm",
        "kalt",
        "stark",
        "schwach",
        "leicht",
        "schwer",
        "sauber",
        "schmutzig",
        "hell",
        "dunkel",
        "freundlich",
        "bekannt",
        "modern",
        "praktisch",
    ]

    # --------------------------------------------------------
    # Reglas de declinación
    # --------------------------------------------------------

    def adjective_ending(adjective, case, gender, determiner):
        """
        Devuelve el adjetivo declinado.

        determiner:
        - definite: der/die/das
        - indefinite: ein/eine/ein
        - none: sin artículo

        Para empezar, el módulo trabaja singular.
        """

        endings = {
            "definite": {
                "Nominativ": {
                    "masculine": "e",
                    "feminine": "e",
                    "neuter": "e",
                },
                "Akkusativ": {
                    "masculine": "en",
                    "feminine": "e",
                    "neuter": "e",
                },
                "Dativ": {
                    "masculine": "en",
                    "feminine": "en",
                    "neuter": "en",
                },
            },
            "indefinite": {
                "Nominativ": {
                    "masculine": "er",
                    "feminine": "e",
                    "neuter": "es",
                },
                "Akkusativ": {
                    "masculine": "en",
                    "feminine": "e",
                    "neuter": "es",
                },
                "Dativ": {
                    "masculine": "en",
                    "feminine": "en",
                    "neuter": "en",
                },
            },
            "none": {
                "Nominativ": {
                    "masculine": "er",
                    "feminine": "e",
                    "neuter": "es",
                },
                "Akkusativ": {
                    "masculine": "en",
                    "feminine": "e",
                    "neuter": "es",
                },
                "Dativ": {
                    "masculine": "em",
                    "feminine": "er",
                    "neuter": "em",
                },
            },
        }

        ending = endings[determiner][case][gender]

        # Algunas palabras necesitan una transformación ortográfica.
        # Para este módulo mantenemos los adjetivos regulares.
        return adjective + ending

    def gender_from_article(article):
        article = normalize(article)

        return {
            "der": "masculine",
            "die": "feminine",
            "das": "neuter",
        }[article]

    def article_for_declension(base_article, case, determiner):
        """
        Artículos definidos e indefinidos en singular.
        """

        gender = gender_from_article(base_article)

        if determiner == "definite":
            mapping = {
                "Nominativ": {
                    "masculine": "der",
                    "feminine": "die",
                    "neuter": "das",
                },
                "Akkusativ": {
                    "masculine": "den",
                    "feminine": "die",
                    "neuter": "das",
                },
                "Dativ": {
                    "masculine": "dem",
                    "feminine": "der",
                    "neuter": "dem",
                },
            }

            return mapping[case][gender]

        if determiner == "indefinite":
            mapping = {
                "Nominativ": {
                    "masculine": "ein",
                    "feminine": "eine",
                    "neuter": "ein",
                },
                "Akkusativ": {
                    "masculine": "einen",
                    "feminine": "eine",
                    "neuter": "ein",
                },
                "Dativ": {
                    "masculine": "einem",
                    "feminine": "einer",
                    "neuter": "einem",
                },
            }

            return mapping[case][gender]

        return ""

    DECLENSION_TEMPLATES = {
        "Nominativ": [
            "{phrase} ist sehr schön.",
            "{phrase} steht dort.",
            "{phrase} ist heute wichtig.",
            "{phrase} kommt heute.",
        ],
        "Akkusativ": [
            "Ich sehe {phrase}.",
            "Ich kaufe {phrase}.",
            "Ich brauche {phrase}.",
            "Ich suche {phrase}.",
        ],
        "Dativ": [
            "Ich fahre mit {phrase}.",
            "Ich spreche mit {phrase}.",
            "Ich arbeite mit {phrase}.",
            "Ich bin bei {phrase}.",
        ],
    }

    def create_declension_question():
        cases = ["Nominativ", "Akkusativ", "Dativ"]

        # Preferimos ambos tipos para practicar:
        # artículo definido y artículo indefinido.
        determiners = ["definite", "indefinite"]

        for _ in range(50):
            selected_case = random.choice(cases)
            determiner = random.choice(determiners)

            noun_row = nouns.sample(
                n=1
            ).iloc[0].to_dict()

            base_article = normalize(noun_row["article"])
            gender = gender_from_article(base_article)

            adjective = random.choice(ADJECTIVES)
            article = article_for_declension(
                base_article,
                selected_case,
                determiner,
            )

            declined_adjective = adjective_ending(
                adjective,
                selected_case,
                gender,
                determiner,
            )

            phrase = (
                f"{article} "
                f"{declined_adjective} "
                f"{noun_row['word']}"
            )

            template = random.choice(
                DECLENSION_TEMPLATES[selected_case]
            )

            sentence = template.format(
                phrase=(
                    "___ ___ "
                    f"{noun_row['word']}"
                )
            )

            question_id = (
                f"{selected_case}|"
                f"{determiner}|"
                f"{noun_row['id']}|"
                f"{adjective}|"
                f"{template}"
            )

            recent = get_recent_question_ids(
                "Declinaciones",
                limit=120,
            )

            if question_id not in recent:
                register_question(
                    "Declinaciones",
                    question_id,
                )

                return {
                    "id": question_id,
                    "case": selected_case,
                    "determiner": determiner,
                    "gender": gender,
                    "noun": noun_row["word"],
                    "noun_id": noun_row["id"],
                    "translation": noun_row["translation"],
                    "adjective": adjective,
                    "correct_article": article,
                    "correct_adjective": declined_adjective,
                    "phrase": phrase,
                    "sentence": sentence,
                }

        # Fallback si se agotó temporalmente el banco.
        selected_case = random.choice(cases)
        determiner = random.choice(determiners)
        noun_row = nouns.sample(n=1).iloc[0].to_dict()

        base_article = normalize(noun_row["article"])
        gender = gender_from_article(base_article)
        adjective = random.choice(ADJECTIVES)

        article = article_for_declension(
            base_article,
            selected_case,
            determiner,
        )

        declined_adjective = adjective_ending(
            adjective,
            selected_case,
            gender,
            determiner,
        )

        template = random.choice(
            DECLENSION_TEMPLATES[selected_case]
        )

        question_id = (
            f"{selected_case}|"
            f"{determiner}|"
            f"{noun_row['id']}|"
            f"{adjective}|"
            f"{template}"
        )

        register_question(
            "Declinaciones",
            question_id,
        )

        return {
            "id": question_id,
            "case": selected_case,
            "determiner": determiner,
            "gender": gender,
            "noun": noun_row["word"],
            "noun_id": noun_row["id"],
            "translation": noun_row["translation"],
            "adjective": adjective,
            "correct_article": article,
            "correct_adjective": declined_adjective,
            "phrase": f"{article} {declined_adjective} {noun_row['word']}",
            "sentence": template.format(
                phrase=(
                    "___ ___ "
                    f"{noun_row['word']}"
                )
            ),
        }

    # --------------------------------------------------------
    # Pregunta actual
    # --------------------------------------------------------

    if st.session_state.questions[module] is None:
        st.session_state.questions[module] = (
            create_declension_question()
        )

    question = st.session_state.questions[module]

    st.subheader("🧩 Declinaciones")

    st.caption(
        "Artículo + adjetivo + sustantivo · "
        "Nominativ · Akkusativ · Dativ"
    )

    st.markdown(
        "Completa **el artículo y la terminación del adjetivo**."
    )

    st.markdown(
        f'<div class="case_sentence">'
        f'{question["sentence"]}'
        f'</div>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        article_input = st.text_input(
            "Artículo",
            key=f"decl_article_input_{question['id']}",
            placeholder="z. B. einem",
        )

    with col2:
        adjective_input = st.text_input(
            "Adjetivo declinado",
            key=f"decl_adjective_input_{question['id']}",
            placeholder=f"z. B. {question['adjective']}en",
        )

    if st.button(
        "Comprobar",
        key=f"check_decl_{question['id']}",
    ):
        article_correct = (
            normalize(article_input)
            == normalize(question["correct_article"])
        )

        adjective_correct = (
            normalize(adjective_input)
            == normalize(question["correct_adjective"])
        )

        correct = article_correct and adjective_correct

        user_answer = (
            f"{article_input.strip()} "
            f"{adjective_input.strip()}"
        ).strip()

        correct_answer = (
            f"{question['correct_article']} "
            f"{question['correct_adjective']}"
        )

        mark_answer(
            module,
            question["noun"],
            st.session_state.level,
            user_answer,
            correct_answer,
            correct,
        )

        st.rerun()

    else:
        if not st.session_state.answered[module]:
            st.info(
                "Ejemplo del tipo de ejercicio: "
                "**mit ___ ___ Auto** → "
                "artículo + adjetivo."
            )

    if st.session_state.answered[module]:

        if st.session_state.last_correct[module]:
            st.success("✅ ¡Correcto!")

        else:
            st.error("❌ Hay una o más partes incorrectas.")

        st.markdown(
            f"### Solución: "
            f"**{question['correct_article']} "
            f"{question['correct_adjective']} "
            f"{question['noun']}**"
        )

        st.info(
            f"**Caso:** {question['case']}  \n"
            f"**Género:** {question['gender']}  \n"
            f"**Tipo de artículo:** "
            f"{'definido' if question['determiner'] == 'definite' else 'indefinido'}"
        )

        if question["determiner"] == "indefinite":
            st.caption(
                "Aquí practicamos la declinación mixta: "
                "el artículo aporta parte de la información "
                "gramatical y el adjetivo toma la terminación "
                "correspondiente."
            )
        else:
            st.caption(
                "Con artículo definido, el adjetivo normalmente "
                "lleva una terminación débil: -e o -en."
            )

        if question["translation"]:
            st.caption(
                f"🇪🇸 Sustantivo: {question['translation']}"
            )

        if st.button(
            "➡️ Siguiente",
            key=f"next_decl_{question['id']}",
        ):
            st.session_state.questions[module] = (
                create_declension_question()
            )
            st.session_state.answered[module] = False
            st.session_state.last_correct[module] = None
            st.session_state.last_answer[module] = ""

            st.rerun()


# ============================================================
# INFORMACIÓN
# ============================================================

st.sidebar.markdown("---")

st.sidebar.caption(
    "Las preguntas recientes se registran en SQLite "
    "para reducir repeticiones."
)
