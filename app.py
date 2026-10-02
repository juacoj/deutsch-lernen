import streamlit as st
import pandas as pd
import sqlite3
import random
import re
import threading
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
    "Verbos",
    "Präteritum",
    "Perfekt",
    "Modalverben",
    "Satzbau",
    "Nebensätze",
    "Präpositionen",
    "Wo / Wohin",
    "Pronomen",
    "Possessivartikel",
    "Komparativ",
    "Adverbien",
    "Nicht / Kein",
    "Fragen",
    "Lückentext",
    "Lesen",
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


def valid_value(value):
    """Devuelve True si un campo de Excel contiene un valor utilizable."""
    if value is None:
        return False
    text = str(value).strip().lower()
    return text not in {"", "-", "—", "–", "none", "nan", "null"}


def make_options(correct, pool, n=3):
    """Crea n alternativas unicas, conservando siempre la correcta."""
    correct = str(correct).strip()
    candidates = []
    seen = {normalize(correct)}

    for value in pool:
        if value is None:
            continue
        value = str(value).strip()
        key = normalize(value)
        if not value or key in seen:
            continue
        seen.add(key)
        candidates.append(value)

    random.shuffle(candidates)
    options = [correct] + candidates[: max(0, n - 1)]
    random.shuffle(options)
    return options


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


@st.cache_data
def get_filtered_vocabulary(level):
    """Filtra por nivel una sola vez y reutiliza el resultado entre reruns."""
    if level == "Todos":
        return df

    level_normalized = str(level).upper().strip()
    mask = df["level"].str.upper().str.strip().eq(level_normalized)
    return df.loc[mask]


# ============================================================
# SQLITE — HISTORIAL Y PROGRESO
# ============================================================

@st.cache_resource
def get_db_connection():
    """
    Mantiene una conexión SQLite reutilizable durante la vida de la app.
    check_same_thread=False permite que Streamlit la reutilice entre
    ejecuciones; DB_LOCK serializa las operaciones para evitar carreras.
    """
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False,
        timeout=10,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


DB_LOCK = threading.Lock()


def init_db():
    conn = get_db_connection()

    with DB_LOCK:
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


init_db()


def save_answer(
    word,
    level,
    module,
    user_answer,
    correct_answer,
    correct,
):
    """Guarda una respuesta sin abrir/cerrar una conexión SQLite nueva."""
    conn = get_db_connection()

    with DB_LOCK:
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


def load_recent_question_cache(per_module=150):
    """
    Carga el historial reciente de todos los módulos con UNA sola consulta.
    Antes se hacía una consulta SQLite cada vez que se generaba una pregunta.
    """
    conn = get_db_connection()
    cache = {module: [] for module in MODULES}

    with DB_LOCK:
        rows = conn.execute(
            """
            SELECT module, question_id
            FROM question_history
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (len(MODULES) * per_module,),
        ).fetchall()

    for module, question_id in rows:
        module = str(module)
        if module not in cache:
            continue
        question_id = str(question_id)
        if question_id not in cache[module] and len(cache[module]) < per_module:
            cache[module].append(question_id)

    return cache


def register_question(module, question_id):
    """Registra una pregunta y actualiza el caché de sesión inmediatamente."""
    question_id = str(question_id)
    conn = get_db_connection()

    with DB_LOCK:
        conn.execute(
            """
            INSERT INTO question_history
            (module, question_id)
            VALUES (?, ?)
            """,
            (module, question_id),
        )
        conn.commit()

    # También actualizamos memoria para no consultar SQLite en la siguiente pregunta.
    recent_cache = st.session_state.setdefault("recent_question_ids", {})
    module_cache = recent_cache.setdefault(module, [])
    module_cache[:] = [qid for qid in module_cache if qid != question_id]
    module_cache.insert(0, question_id)
    del module_cache[150:]


def get_recent_question_ids(module, limit=40):
    """Obtiene preguntas recientes desde memoria; SQLite solo se consulta al iniciar la sesión."""
    recent_cache = st.session_state.get("recent_question_ids")

    if recent_cache is None:
        recent_cache = load_recent_question_cache()
        st.session_state.recent_question_ids = recent_cache

    return set(recent_cache.get(module, [])[:limit])


def choose_from_dataframe(
    available,
    module,
    id_column="id",
    recent_limit=40,
):
    """
    Selecciona una pregunta evitando las últimas N preguntas usadas.

    Optimizado para no copiar el DataFrame completo ni hacer una consulta
    SQLite en cada pregunta.
    """
    if available.empty:
        return None

    recent_ids = get_recent_question_ids(
        module,
        limit=recent_limit,
    )

    if id_column in available.columns:
        ids = available[id_column].astype(str)
        candidates = available.loc[~ids.isin(recent_ids)]
    else:
        # Fallback para DataFrames que no tienen columna id.
        candidate_positions = [
            i for i, value in enumerate(available.index.astype(str))
            if value not in recent_ids
        ]
        candidates = (
            available.iloc[candidate_positions]
            if candidate_positions
            else available
        )

    # Si ya se utilizaron todas, permitimos reutilizar.
    if candidates.empty:
        candidates = available

    # Elegir por posición es sensiblemente más ligero que DataFrame.sample().
    position = random.randrange(len(candidates))
    selected = candidates.iloc[position]

    question_id = (
        str(selected[id_column])
        if id_column in available.columns
        else str(selected.name)
    )

    register_question(module, question_id)

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

# Historial reciente cargado una sola vez por sesión.
# Esto evita consultas SQLite repetidas al generar preguntas.
if "recent_question_ids" not in st.session_state:
    st.session_state.recent_question_ids = load_recent_question_cache()


# ============================================================
# FUNCIONES DE ESTADO
# ============================================================

def reset_module(module, available=None):
    st.session_state.questions[module] = None
    st.session_state.answered[module] = False
    st.session_state.last_correct[module] = None
    st.session_state.last_answer[module] = ""

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


filtered = get_filtered_vocabulary(st.session_state.level)


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

    # Tres alternativas aleatorias, en ambas direcciones.
    if "options" not in word:
        if word["direction"] == "de_to_es":
            pool = vocab["translation"].tolist()
            word["options"] = make_options(correct_answer, pool, 3)
        else:
            pool = vocab["word"].tolist()
            word["options"] = make_options(correct_answer, pool, 3)

    if not st.session_state.answered[module]:

        choice = st.radio(
            "Elige la respuesta correcta:",
            word["options"],
            key=f"vocab_choice_{word['id']}",
        )

        if st.button(
            "Comprobar",
            key=f"check_vocab_{word['id']}",
            use_container_width=True,
        ):
            correct = normalize(choice) == normalize(correct_answer)

            mark_answer(
                module,
                word["word"],
                word["level"],
                choice,
                correct_answer,
                correct,
            )

            st.rerun()

    else:

        if st.session_state.last_correct[module]:
            st.success("✅ ¡Correcto!")
        else:
            st.error(
                f"❌ La respuesta correcta es: **{correct_answer}**"
            )

        if word["example_de"]:
            st.info(f"📝 {word['example_de']}")

        if word["example_es"]:
            st.caption(f"🇪🇸 {word['example_es']}")

        if st.button(
            "➡️ Siguiente",
            key=f"next_vocab_{word['id']}",
        ):
            next_question(module, vocab)


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

        input_key = f"plural_input_{word['id']}"
        german_keyboard(input_key)

        plural = st.text_input(
            "Escribe el plural:",
            key=input_key,
        )

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

        input_key = f"particip_input_{word['id']}"
        german_keyboard(input_key)

        particip = st.text_input(
            "Escribe el Partizip II:",
            key=input_key,
        )

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

        input_key = f"case_input_{question['id']}"
        german_keyboard(input_key)

        answer = st.text_input(
            "Artículo:",
            key=input_key,
        )

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
        "Completa **el artículo y la terminación del adjetivo** según las pistas."
    )

    # Pistas visibles: ayudan a saber qué construcción gramatical se pide
    # sin revelar la respuesta concreta.
    gender_label = {
        "masculine": "masculino",
        "feminine": "femenino",
        "neuter": "neutro",
    }.get(question["gender"], question["gender"])
    determiner_label = (
        "definido"
        if question["determiner"] == "definite"
        else "indefinido"
    )

    st.info(
        f"**🇩🇪 Caso:** {question['case']}  ·  "
        f"**Género:** {gender_label}  ·  "
        f"**Tipo de artículo:** {determiner_label}"
    )

    if question["translation"]:
        st.caption(f"🇪🇸 Sustantivo: {question['translation']}")

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
            placeholder="z. B. einem / eine / den",
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
# MÓDULOS A2 — 7 A 22
# ============================================================

elif module in MODULES[6:]:

    # --------------------------------------------------------
    # Helper local para preguntas de completar.
    # Cada pregunta utiliza una key propia, evitando errores
    # de Streamlit con st.session_state después de instanciar
    # un widget.
    # --------------------------------------------------------

    def simple_question(
        question_id,
        prompt,
        correct,
        title,
        caption="",
        explanation="",
        answer_label="Respuesta",
        options=None,
    ):
        if st.session_state.questions[module] is None:
            register_question(module, question_id)

            st.session_state.questions[module] = {
                "id": question_id,
                "prompt": prompt,
                "correct": correct,
                "caption": caption,
                "explanation": explanation,
            }

        q = st.session_state.questions[module]

        st.subheader(title)

        if q.get("caption"):
            st.caption(q["caption"])

        st.markdown(
            f'<div class="case_sentence">{q["prompt"]}</div>',
            unsafe_allow_html=True,
        )

        if options:
            user = st.radio(
                answer_label,
                options,
                key=f"a2_choice_{module}_{q['id']}",
            )
        else:
            input_key = f"a2_input_{module}_{q['id']}"
            german_keyboard(input_key)

            user = st.text_input(
                answer_label,
                key=input_key,
            )

        if st.button(
            "Comprobar",
            key=f"a2_check_{module}_{q['id']}",
            use_container_width=True,
        ):
            correct_answer = normalize(q["correct"])
            user_answer = normalize(user)

            ok = user_answer == correct_answer

            mark_answer(
                module,
                q["prompt"],
                st.session_state.level,
                user,
                q["correct"],
                ok,
            )

            st.rerun()

        if st.session_state.answered[module]:

            if st.session_state.last_correct[module]:
                st.success("✅ ¡Correcto!")
            else:
                st.error(
                    f"❌ Correcto: **{q['correct']}**"
                )

            if q.get("explanation"):
                st.info(q["explanation"])

            if st.button(
                "➡️ Siguiente",
                key=f"a2_next_{module}_{q['id']}",
            ):
                return True

        return False

    def choose_static(items, module_name):
        recent = get_recent_question_ids(
            module_name,
            limit=50,
        )

        available = [
            item
            for item in items
            if item["id"] not in recent
        ]

        if not available:
            available = items

        return random.choice(available)

    # --------------------------------------------------------
    # 7 — VERBOS
    # --------------------------------------------------------

    if module == "Verbos":

        pronouns = [
            "ich",
            "du",
            "er/sie/es",
            "wir",
            "ihr",
            "sie/Sie",
        ]

        special = {
            "sein": {
                "ich": "bin",
                "du": "bist",
                "er/sie/es": "ist",
                "wir": "sind",
                "ihr": "seid",
                "sie/Sie": "sind",
            },
            "haben": {
                "ich": "habe",
                "du": "hast",
                "er/sie/es": "hat",
                "wir": "haben",
                "ihr": "habt",
                "sie/Sie": "haben",
            },
            "werden": {
                "ich": "werde",
                "du": "wirst",
                "er/sie/es": "wird",
                "wir": "werden",
                "ihr": "werdet",
                "sie/Sie": "werden",
            },
        }

        verbs = filtered[
            filtered["part_of_speech"]
            .fillna("")
            .str.lower()
            .str.strip()
            .eq("verb")
        ].copy()

        if verbs.empty:
            st.warning("No hay verbos disponibles.")
            st.stop()

        if st.session_state.questions[module] is None:

            row = choose_from_dataframe(
                verbs,
                module,
                recent_limit=40,
            )

            verb = normalize(row["word"])
            pronoun = random.choice(pronouns)

            if verb in special:
                answer = special[verb][pronoun]
            else:
                stem = verb[:-2] if verb.endswith("en") else verb

                endings = {
                    "ich": "e",
                    "du": "st",
                    "er/sie/es": "t",
                    "wir": "en",
                    "ihr": "t",
                    "sie/Sie": "en",
                }

                answer = stem + endings[pronoun]

            st.session_state.questions[module] = {
                "id": f"verb|{row['id']}|{pronoun}",
                "prompt": f"{pronoun} ___",
                "correct": answer,
                "caption": f"Infinitivo: {row['word']}",
                "explanation": (
                    f"🇪🇸 {row['translation']}"
                    if row["translation"]
                    else ""
                ),
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "🔤 Verbos",
            q["caption"],
            q["explanation"],
            "Verbo conjugado",
        )

        if st.session_state.answered[module]:
            if st.button(
                "➡️ Nueva pregunta",
                key=f"verb_next_{q['id']}",
            ):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 8 — PRÄTERITUM
    # --------------------------------------------------------

    elif module == "Präteritum":

        forms = {
            "sein": {
                "ich": "war",
                "du": "warst",
                "er/sie/es": "war",
                "wir": "waren",
                "ihr": "wart",
                "sie/Sie": "waren",
            },
            "haben": {
                "ich": "hatte",
                "du": "hattest",
                "er/sie/es": "hatte",
                "wir": "hatten",
                "ihr": "hattet",
                "sie/Sie": "hatten",
            },
            "können": {
                "ich": "konnte",
                "du": "konntest",
                "er/sie/es": "konnte",
                "wir": "konnten",
                "ihr": "konntet",
                "sie/Sie": "konnten",
            },
            "müssen": {
                "ich": "musste",
                "du": "musstest",
                "er/sie/es": "musste",
                "wir": "mussten",
                "ihr": "musstet",
                "sie/Sie": "mussten",
            },
            "wollen": {
                "ich": "wollte",
                "du": "wolltest",
                "er/sie/es": "wollte",
                "wir": "wollten",
                "ihr": "wolltet",
                "sie/Sie": "wollten",
            },
            "gehen": {
                "ich": "ging",
                "du": "gingst",
                "er/sie/es": "ging",
                "wir": "gingen",
                "ihr": "gingt",
                "sie/Sie": "gingen",
            },
            "kommen": {
                "ich": "kam",
                "du": "kamst",
                "er/sie/es": "kam",
                "wir": "kamen",
                "ihr": "kamt",
                "sie/Sie": "kamen",
            },
        }

        if st.session_state.questions[module] is None:

            verb = random.choice(list(forms))
            pronoun = random.choice(list(forms[verb]))

            qid = f"preteritum|{verb}|{pronoun}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": f"Gestern: {pronoun} ___",
                "correct": forms[verb][pronoun],
                "caption": f"Infinitivo: {verb}",
                "explanation": "En A2 son especialmente importantes war, hatte y los modales en Präteritum.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "⏳ Präteritum",
            q["caption"],
            q["explanation"],
            "Präteritum",
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"pr_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 9 — PERFEKT
    # --------------------------------------------------------

    elif module == "Perfekt":

        sein_verbs = {
            "gehen",
            "fahren",
            "kommen",
            "reisen",
            "laufen",
            "bleiben",
            "fliegen",
            "aufstehen",
            "ankommen",
        }

        verbs = filtered[
            filtered["part_of_speech"]
            .fillna("")
            .str.lower()
            .str.strip()
            .eq("verb")
        ].copy()

        verbs = verbs[
            verbs["partizip_II"].apply(valid_value)
        ]

        if verbs.empty:
            st.warning("No hay verbos con Partizip II.")
            st.stop()

        if st.session_state.questions[module] is None:

            row = choose_from_dataframe(
                verbs,
                module,
                recent_limit=50,
            )

            verb = normalize(row["word"])

            auxiliary = (
                "sein"
                if verb in sein_verbs
                else "haben"
            )

            qid = f"perfekt|{row['id']}"

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": f"Ich ___ {row['partizip_II']}.",
                "correct": auxiliary,
                "caption": f"Infinitivo: {row['word']}",
                "explanation": (
                    f"Frase: Ich {auxiliary} "
                    f"{row['partizip_II']}."
                ),
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "🕐 Perfekt",
            q["caption"],
            q["explanation"],
            "¿Qué auxiliar corresponde?",
            ["haben", "sein"],
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"pf_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 10 — MODALVERBEN
    # --------------------------------------------------------

    elif module == "Modalverben":

        forms = {
            "können": ["kann", "kannst", "kann", "können", "könnt", "können"],
            "müssen": ["muss", "musst", "muss", "müssen", "müsst", "müssen"],
            "wollen": ["will", "willst", "will", "wollen", "wollt", "wollen"],
            "sollen": ["soll", "sollst", "soll", "sollen", "sollt", "sollen"],
            "dürfen": ["darf", "darfst", "darf", "dürfen", "dürft", "dürfen"],
            "mögen": ["mag", "magst", "mag", "mögen", "mögt", "mögen"],
        }

        pronouns = [
            "ich", "du", "er/sie/es",
            "wir", "ihr", "sie/Sie",
        ]

        if st.session_state.questions[module] is None:
            modal = random.choice(list(forms))
            index = pronouns.index(
                random.choice(pronouns)
            )
            pronoun = pronouns[index]

            qid = f"modal|{modal}|{pronoun}"

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": f"{pronoun} ___ heute arbeiten.",
                "correct": forms[modal][index],
                "caption": f"Infinitivo: {modal}",
                "explanation": "El infinitivo principal va al final: Ich muss heute arbeiten.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "⚙️ Modalverben",
            q["caption"],
            q["explanation"],
            "Modalverb conjugado",
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"modal_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 11 — SATZBAU
    # --------------------------------------------------------

    elif module == "Satzbau":

        exercises = [
            ('heute / ein neues Buch / Ich / kaufe', 'Ich kaufe ein neues Buch heute.'),
            ('morgen / Deutsch / Du / lernst', 'Du lernst Deutsch morgen.'),
            ('am Montag / eine Suppe / Er / kocht', 'Er kocht eine Suppe am Montag.'),
            ('am Abend / meine Freunde / Sie / besucht', 'Sie besucht meine Freunde am Abend.'),
            ('am Wochenende / Fußball / Wir / spielen', 'Wir spielen Fußball am Wochenende.'),
            ('jeden Morgen / einen Kaffee / Ihr / trinkt', 'Ihr trinkt einen Kaffee jeden Morgen.'),
            ('nach der Arbeit / die Hausaufgaben / Anna / macht', 'Anna macht die Hausaufgaben nach der Arbeit.'),
            ('um acht Uhr / die Zeitung / Paul / liest', 'Paul liest die Zeitung um acht Uhr.'),
            ('am Freitag / das Museum / Meine Schwester / besichtigt', 'Meine Schwester besichtigt das Museum am Freitag.'),
            ('nächste Woche / einen Kollegen / Meine Eltern / treffen', 'Meine Eltern treffen einen Kollegen nächste Woche.'),
            ('morgen / ein neues Buch / Er / kauft', 'Er kauft ein neues Buch morgen.'),
            ('am Montag / Deutsch / Sie / lernt', 'Sie lernt Deutsch am Montag.'),
            ('am Abend / eine Suppe / Wir / kochen', 'Wir kochen eine Suppe am Abend.'),
            ('am Wochenende / meine Freunde / Ihr / besucht', 'Ihr besucht meine Freunde am Wochenende.'),
            ('jeden Morgen / Fußball / Anna / spielt', 'Anna spielt Fußball jeden Morgen.'),
            ('nach der Arbeit / einen Kaffee / Paul / trinkt', 'Paul trinkt einen Kaffee nach der Arbeit.'),
            ('um acht Uhr / die Hausaufgaben / Meine Schwester / macht', 'Meine Schwester macht die Hausaufgaben um acht Uhr.'),
            ('am Freitag / die Zeitung / Meine Eltern / lesen', 'Meine Eltern lesen die Zeitung am Freitag.'),
            ('nächste Woche / das Museum / Ich / besichtige', 'Ich besichtige das Museum nächste Woche.'),
            ('heute / einen Kollegen / Du / triffst', 'Du triffst einen Kollegen heute.'),
            ('am Montag / ein neues Buch / Wir / kaufen', 'Wir kaufen ein neues Buch am Montag.'),
            ('am Abend / Deutsch / Ihr / lernt', 'Ihr lernt Deutsch am Abend.'),
            ('am Wochenende / eine Suppe / Anna / kocht', 'Anna kocht eine Suppe am Wochenende.'),
            ('jeden Morgen / meine Freunde / Paul / besucht', 'Paul besucht meine Freunde jeden Morgen.'),
            ('nach der Arbeit / Fußball / Meine Schwester / spielt', 'Meine Schwester spielt Fußball nach der Arbeit.'),
            ('um acht Uhr / einen Kaffee / Meine Eltern / trinken', 'Meine Eltern trinken einen Kaffee um acht Uhr.'),
            ('am Freitag / die Hausaufgaben / Ich / mache', 'Ich mache die Hausaufgaben am Freitag.'),
            ('nächste Woche / die Zeitung / Du / liest', 'Du liest die Zeitung nächste Woche.'),
            ('heute / das Museum / Er / besichtigt', 'Er besichtigt das Museum heute.'),
            ('morgen / einen Kollegen / Sie / trifft', 'Sie trifft einen Kollegen morgen.'),
            ('am Abend / ein neues Buch / Anna / kauft', 'Anna kauft ein neues Buch am Abend.'),
            ('am Wochenende / Deutsch / Paul / lernt', 'Paul lernt Deutsch am Wochenende.'),
            ('jeden Morgen / eine Suppe / Meine Schwester / kocht', 'Meine Schwester kocht eine Suppe jeden Morgen.'),
            ('nach der Arbeit / meine Freunde / Meine Eltern / besuchen', 'Meine Eltern besuchen meine Freunde nach der Arbeit.'),
            ('um acht Uhr / Fußball / Ich / spiele', 'Ich spiele Fußball um acht Uhr.'),
            ('am Freitag / einen Kaffee / Du / trinkst', 'Du trinkst einen Kaffee am Freitag.'),
            ('nächste Woche / die Hausaufgaben / Er / macht', 'Er macht die Hausaufgaben nächste Woche.'),
            ('heute / die Zeitung / Sie / liest', 'Sie liest die Zeitung heute.'),
            ('morgen / das Museum / Wir / besichtigen', 'Wir besichtigen das Museum morgen.'),
            ('am Montag / einen Kollegen / Ihr / trefft', 'Ihr trefft einen Kollegen am Montag.'),
            ('am Wochenende / ein neues Buch / Meine Schwester / kauft', 'Meine Schwester kauft ein neues Buch am Wochenende.'),
            ('jeden Morgen / Deutsch / Meine Eltern / lernen', 'Meine Eltern lernen Deutsch jeden Morgen.'),
            ('nach der Arbeit / eine Suppe / Ich / koche', 'Ich koche eine Suppe nach der Arbeit.'),
            ('um acht Uhr / meine Freunde / Du / besuchst', 'Du besuchst meine Freunde um acht Uhr.'),
            ('am Freitag / Fußball / Er / spielt', 'Er spielt Fußball am Freitag.'),
            ('nächste Woche / einen Kaffee / Sie / trinkt', 'Sie trinkt einen Kaffee nächste Woche.'),
            ('heute / die Hausaufgaben / Wir / machen', 'Wir machen die Hausaufgaben heute.'),
            ('morgen / die Zeitung / Ihr / lest', 'Ihr lest die Zeitung morgen.'),
            ('am Montag / das Museum / Anna / besichtigt', 'Anna besichtigt das Museum am Montag.'),
            ('am Abend / einen Kollegen / Paul / trifft', 'Paul trifft einen Kollegen am Abend.'),
            ('in die Stadt / am Montag / Ihr / geht', 'Ihr geht in die Stadt am Montag.'),
            ('zur Arbeit / am Abend / Anna / fährt', 'Anna fährt zur Arbeit am Abend.'),
            ('zu Hause / am Wochenende / Paul / bleibt', 'Paul bleibt zu Hause am Wochenende.'),
            ('im Park / jeden Morgen / Meine Schwester / läuft', 'Meine Schwester läuft im Park jeden Morgen.'),
            ('nach Hause / nach der Arbeit / Meine Eltern / kommen', 'Meine Eltern kommen nach Hause nach der Arbeit.'),
            ('zum Bahnhof / um acht Uhr / Ich / fahre', 'Ich fahre zum Bahnhof um acht Uhr.'),
            ('in die Bibliothek / am Freitag / Du / gehst', 'Du gehst in die Bibliothek am Freitag.'),
            ('im Büro / nächste Woche / Er / bleibt', 'Er bleibt im Büro nächste Woche.'),
            ('nach Zürich / heute / Sie / fährt', 'Sie fährt nach Zürich heute.'),
            ('ins Café / morgen / Wir / gehen', 'Wir gehen ins Café morgen.'),
            ('in die Stadt / am Abend / Paul / geht', 'Paul geht in die Stadt am Abend.'),
            ('zur Arbeit / am Wochenende / Meine Schwester / fährt', 'Meine Schwester fährt zur Arbeit am Wochenende.'),
            ('zu Hause / jeden Morgen / Meine Eltern / bleiben', 'Meine Eltern bleiben zu Hause jeden Morgen.'),
            ('im Park / nach der Arbeit / Ich / laufe', 'Ich laufe im Park nach der Arbeit.'),
            ('nach Hause / um acht Uhr / Du / kommst', 'Du kommst nach Hause um acht Uhr.'),
            ('zum Bahnhof / am Freitag / Er / fährt', 'Er fährt zum Bahnhof am Freitag.'),
            ('in die Bibliothek / nächste Woche / Sie / geht', 'Sie geht in die Bibliothek nächste Woche.'),
            ('im Büro / heute / Wir / bleiben', 'Wir bleiben im Büro heute.'),
            ('nach Zürich / morgen / Ihr / fahrt', 'Ihr fahrt nach Zürich morgen.'),
            ('ins Café / am Montag / Anna / geht', 'Anna geht ins Café am Montag.'),
            ('in die Stadt / am Wochenende / Meine Eltern / gehen', 'Meine Eltern gehen in die Stadt am Wochenende.'),
            ('zur Arbeit / jeden Morgen / Ich / fahre', 'Ich fahre zur Arbeit jeden Morgen.'),
            ('zu Hause / nach der Arbeit / Du / bleibst', 'Du bleibst zu Hause nach der Arbeit.'),
            ('im Park / um acht Uhr / Er / läuft', 'Er läuft im Park um acht Uhr.'),
            ('nach Hause / am Freitag / Sie / kommt', 'Sie kommt nach Hause am Freitag.'),
            ('zum Bahnhof / nächste Woche / Wir / fahren', 'Wir fahren zum Bahnhof nächste Woche.'),
            ('in die Bibliothek / heute / Ihr / geht', 'Ihr geht in die Bibliothek heute.'),
            ('im Büro / morgen / Anna / bleibt', 'Anna bleibt im Büro morgen.'),
            ('nach Zürich / am Montag / Paul / fährt', 'Paul fährt nach Zürich am Montag.'),
            ('ins Café / am Abend / Meine Schwester / geht', 'Meine Schwester geht ins Café am Abend.'),
            ('in die Stadt / jeden Morgen / Du / gehst', 'Du gehst in die Stadt jeden Morgen.'),
            ('zur Arbeit / nach der Arbeit / Er / fährt', 'Er fährt zur Arbeit nach der Arbeit.'),
            ('zu Hause / um acht Uhr / Sie / bleibt', 'Sie bleibt zu Hause um acht Uhr.'),
            ('im Park / am Freitag / Wir / laufen', 'Wir laufen im Park am Freitag.'),
            ('nach Hause / nächste Woche / Ihr / kommt', 'Ihr kommt nach Hause nächste Woche.'),
            ('zum Bahnhof / heute / Anna / fährt', 'Anna fährt zum Bahnhof heute.'),
            ('in die Bibliothek / morgen / Paul / geht', 'Paul geht in die Bibliothek morgen.'),
            ('im Büro / am Montag / Meine Schwester / bleibt', 'Meine Schwester bleibt im Büro am Montag.'),
            ('nach Zürich / am Abend / Meine Eltern / fahren', 'Meine Eltern fahren nach Zürich am Abend.'),
            ('ins Café / am Wochenende / Ich / gehe', 'Ich gehe ins Café am Wochenende.'),
            ('in die Stadt / nach der Arbeit / Sie / geht', 'Sie geht in die Stadt nach der Arbeit.'),
            ('zur Arbeit / um acht Uhr / Wir / fahren', 'Wir fahren zur Arbeit um acht Uhr.'),
            ('zu Hause / am Freitag / Ihr / bleibt', 'Ihr bleibt zu Hause am Freitag.'),
            ('im Park / nächste Woche / Anna / läuft', 'Anna läuft im Park nächste Woche.'),
            ('nach Hause / heute / Paul / kommt', 'Paul kommt nach Hause heute.'),
            ('zum Bahnhof / morgen / Meine Schwester / fährt', 'Meine Schwester fährt zum Bahnhof morgen.'),
            ('in die Bibliothek / am Montag / Meine Eltern / gehen', 'Meine Eltern gehen in die Bibliothek am Montag.'),
            ('im Büro / am Abend / Ich / bleibe', 'Ich bleibe im Büro am Abend.'),
            ('nach Zürich / am Wochenende / Du / fährst', 'Du fährst nach Zürich am Wochenende.'),
            ('ins Café / jeden Morgen / Er / geht', 'Er geht ins Café jeden Morgen.'),
            ('nach Hause / du / Wann / kommst', 'Wann du kommst nach Hause?'),
            ('zum Bahnhof / du / Wann / kommst', 'Wann du kommst zum Bahnhof?'),
            ('ins Büro / du / Wann / kommst', 'Wann du kommst ins Büro?'),
            ('zur Schule / du / Wann / kommst', 'Wann du kommst zur Schule?'),
            ('nach Zürich / du / Wann / kommst', 'Wann du kommst nach Zürich?'),
            ('im Büro / du / Wo / arbeitest', 'Wo du arbeitest im Büro?'),
            ('am Montag / du / Wo / arbeitest', 'Wo du arbeitest am Montag?'),
            ('in Zürich / du / Wo / arbeitest', 'Wo du arbeitest in Zürich?'),
            ('am Wochenende / du / Wo / arbeitest', 'Wo du arbeitest am Wochenende?'),
            ('heute / du / Wo / arbeitest', 'Wo du arbeitest heute?'),
            ('im Supermarkt / du / Was / kaufst', 'Was du kaufst im Supermarkt?'),
            ('heute / du / Was / kaufst', 'Was du kaufst heute?'),
            ('für das Abendessen / du / Was / kaufst', 'Was du kaufst für das Abendessen?'),
            ('am Samstag / du / Was / kaufst', 'Was du kaufst am Samstag?'),
            ('für deine Mutter / du / Was / kaufst', 'Was du kaufst für deine Mutter?'),
            ('Deutsch / du / Warum / lernst', 'Warum du lernst Deutsch?'),
            ('am Abend / du / Warum / lernst', 'Warum du lernst am Abend?'),
            ('jeden Tag / du / Warum / lernst', 'Warum du lernst jeden Tag?'),
            ('so viel / du / Warum / lernst', 'Warum du lernst so viel?'),
            ('zu Hause / du / Warum / lernst', 'Warum du lernst zu Hause?'),
            ('zur Arbeit / du / Wie / fährst', 'Wie du fährst zur Arbeit?'),
            ('nach Zürich / du / Wie / fährst', 'Wie du fährst nach Zürich?'),
            ('zum Bahnhof / du / Wie / fährst', 'Wie du fährst zum Bahnhof?'),
            ('nach Hause / du / Wie / fährst', 'Wie du fährst nach Hause?'),
            ('in die Stadt / du / Wie / fährst', 'Wie du fährst in die Stadt?'),
            ('mit dem Kurs / ihr / Wann / beginnt', 'Wann ihr beginnt mit dem Kurs?'),
            ('mit der Arbeit / ihr / Wann / beginnt', 'Wann ihr beginnt mit der Arbeit?'),
            ('mit dem Essen / ihr / Wann / beginnt', 'Wann ihr beginnt mit dem Essen?'),
            ('mit dem Training / ihr / Wann / beginnt', 'Wann ihr beginnt mit dem Training?'),
            ('mit dem Unterricht / ihr / Wann / beginnt', 'Wann ihr beginnt mit dem Unterricht?'),
            ('in Zürich / Anna / Wo / wohnt', 'Wo Anna wohnt in Zürich?'),
            ('seit zwei Jahren / Anna / Wo / wohnt', 'Wo Anna wohnt seit zwei Jahren?'),
            ('mit ihrer Familie / Anna / Wo / wohnt', 'Wo Anna wohnt mit ihrer Familie?'),
            ('jetzt / Anna / Wo / wohnt', 'Wo Anna wohnt jetzt?'),
            ('am Wochenende / Anna / Wo / wohnt', 'Wo Anna wohnt am Wochenende?'),
            ('am Wochenende / ihr / Was / macht', 'Was ihr macht am Wochenende?'),
            ('nach der Arbeit / ihr / Was / macht', 'Was ihr macht nach der Arbeit?'),
            ('heute Abend / ihr / Was / macht', 'Was ihr macht heute Abend?'),
            ('in Zürich / ihr / Was / macht', 'Was ihr macht in Zürich?'),
            ('im Urlaub / ihr / Was / macht', 'Was ihr macht im Urlaub?'),
            ('zu Hause / sie / Warum / bleibt', 'Warum sie bleibt zu Hause?'),
            ('heute im Büro / sie / Warum / bleibt', 'Warum sie bleibt heute im Büro?'),
            ('am Wochenende / sie / Warum / bleibt', 'Warum sie bleibt am Wochenende?'),
            ('so lange / sie / Warum / bleibt', 'Warum sie bleibt so lange?'),
            ('in Zürich / sie / Warum / bleibt', 'Warum sie bleibt in Zürich?'),
            ('Deutsch / du / Wie / lernst', 'Wie du lernst Deutsch?'),
            ('neue Wörter / du / Wie / lernst', 'Wie du lernst neue Wörter?'),
            ('für die Prüfung / du / Wie / lernst', 'Wie du lernst für die Prüfung?'),
            ('jeden Abend / du / Wie / lernst', 'Wie du lernst jeden Abend?'),
            ('am besten / du / Wie / lernst', 'Wie du lernst am besten?'),
            ('arbeiten / heute / Ich / muss', 'Ich muss heute arbeiten.'),
            ('kommen / morgen / Du / kannst', 'Du kannst morgen kommen.'),
            ('reisen / am Wochenende / Er / will', 'Er will am Wochenende reisen.'),
            ('trinken / einen Kaffee / Sie / möchte', 'Sie möchte einen Kaffee trinken.'),
            ('anfangen / um acht Uhr / Wir / sollen', 'Wir sollen um acht Uhr anfangen.'),
            ('parken / hier / Ihr / dürft', 'Ihr dürft hier parken.'),
            ('schwimmen / sehr gut / Anna / kann', 'Anna kann sehr gut schwimmen.'),
            ('kochen / am Abend / Paul / will', 'Paul will am Abend kochen.'),
            ('essen / in Zürich / Meine Schwester / möchte', 'Meine Schwester möchte in Zürich essen.'),
            ('fahren / morgen / Meine Eltern / müssen', 'Meine Eltern müssen morgen fahren.'),
            ('arbeiten / heute im Büro / Ich / muss', 'Ich muss heute im Büro arbeiten.'),
            ('kommen / morgen im Büro / Du / kannst', 'Du kannst morgen im Büro kommen.'),
            ('reisen / am Wochenende im Büro / Er / will', 'Er will am Wochenende im Büro reisen.'),
            ('trinken / einen Kaffee im Büro / Sie / möchte', 'Sie möchte einen Kaffee im Büro trinken.'),
            ('anfangen / um acht Uhr im Büro / Wir / sollen', 'Wir sollen um acht Uhr im Büro anfangen.'),
            ('parken / hier im Büro / Ihr / dürft', 'Ihr dürft hier im Büro parken.'),
            ('schwimmen / sehr gut im Büro / Anna / kann', 'Anna kann sehr gut im Büro schwimmen.'),
            ('kochen / am Abend im Büro / Paul / will', 'Paul will am Abend im Büro kochen.'),
            ('essen / in Zürich im Büro / Meine Schwester / möchte', 'Meine Schwester möchte in Zürich im Büro essen.'),
            ('fahren / morgen im Büro / Meine Eltern / müssen', 'Meine Eltern müssen morgen im Büro fahren.'),
            ('arbeiten / heute zu Hause / Ich / muss', 'Ich muss heute zu Hause arbeiten.'),
            ('kommen / morgen zu Hause / Du / kannst', 'Du kannst morgen zu Hause kommen.'),
            ('reisen / am Wochenende zu Hause / Er / will', 'Er will am Wochenende zu Hause reisen.'),
            ('trinken / einen Kaffee zu Hause / Sie / möchte', 'Sie möchte einen Kaffee zu Hause trinken.'),
            ('anfangen / um acht Uhr zu Hause / Wir / sollen', 'Wir sollen um acht Uhr zu Hause anfangen.'),
            ('parken / hier zu Hause / Ihr / dürft', 'Ihr dürft hier zu Hause parken.'),
            ('schwimmen / sehr gut zu Hause / Anna / kann', 'Anna kann sehr gut zu Hause schwimmen.'),
            ('kochen / am Abend zu Hause / Paul / will', 'Paul will am Abend zu Hause kochen.'),
            ('essen / in Zürich zu Hause / Meine Schwester / möchte', 'Meine Schwester möchte in Zürich zu Hause essen.'),
            ('fahren / morgen zu Hause / Meine Eltern / müssen', 'Meine Eltern müssen morgen zu Hause fahren.'),
            ('arbeiten / heute in der Stadt / Ich / muss', 'Ich muss heute in der Stadt arbeiten.'),
            ('kommen / morgen in der Stadt / Du / kannst', 'Du kannst morgen in der Stadt kommen.'),
            ('reisen / am Wochenende in der Stadt / Er / will', 'Er will am Wochenende in der Stadt reisen.'),
            ('trinken / einen Kaffee in der Stadt / Sie / möchte', 'Sie möchte einen Kaffee in der Stadt trinken.'),
            ('anfangen / um acht Uhr in der Stadt / Wir / sollen', 'Wir sollen um acht Uhr in der Stadt anfangen.'),
            ('parken / hier in der Stadt / Ihr / dürft', 'Ihr dürft hier in der Stadt parken.'),
            ('schwimmen / sehr gut in der Stadt / Anna / kann', 'Anna kann sehr gut in der Stadt schwimmen.'),
            ('kochen / am Abend in der Stadt / Paul / will', 'Paul will am Abend in der Stadt kochen.'),
            ('essen / in Zürich in der Stadt / Meine Schwester / möchte', 'Meine Schwester möchte in Zürich in der Stadt essen.'),
            ('fahren / morgen in der Stadt / Meine Eltern / müssen', 'Meine Eltern müssen morgen in der Stadt fahren.'),
            ('arbeiten / heute mit Freunden / Ich / muss', 'Ich muss heute mit Freunden arbeiten.'),
            ('kommen / morgen mit Freunden / Du / kannst', 'Du kannst morgen mit Freunden kommen.'),
            ('reisen / am Wochenende mit Freunden / Er / will', 'Er will am Wochenende mit Freunden reisen.'),
            ('trinken / einen Kaffee mit Freunden / Sie / möchte', 'Sie möchte einen Kaffee mit Freunden trinken.'),
            ('anfangen / um acht Uhr mit Freunden / Wir / sollen', 'Wir sollen um acht Uhr mit Freunden anfangen.'),
            ('parken / hier mit Freunden / Ihr / dürft', 'Ihr dürft hier mit Freunden parken.'),
            ('schwimmen / sehr gut mit Freunden / Anna / kann', 'Anna kann sehr gut mit Freunden schwimmen.'),
            ('kochen / am Abend mit Freunden / Paul / will', 'Paul will am Abend mit Freunden kochen.'),
            ('essen / in Zürich mit Freunden / Meine Schwester / möchte', 'Meine Schwester möchte in Zürich mit Freunden essen.'),
            ('fahren / morgen mit Freunden / Meine Eltern / müssen', 'Meine Eltern müssen morgen mit Freunden fahren.'),
            ('auf / um sieben Uhr / Ich / stehe', 'Ich stehe um sieben Uhr auf.'),
            ('an / deine Mutter / Du / rufst', 'Du rufst deine Mutter an.'),
            ('ein / im Supermarkt / Er / kauft', 'Er kauft im Supermarkt ein.'),
            ('auf / das Zimmer / Sie / räumt', 'Sie räumt das Zimmer auf.'),
            ('an / um neun Uhr / Wir / fangen', 'Wir fangen um neun Uhr an.'),
            ('fern / am Abend / Ihr / seht', 'Ihr seht am Abend fern.'),
            ('zurück / morgen / Anna / kommt', 'Anna kommt morgen zurück.'),
            ('zu / die Tür / Paul / macht', 'Paul macht die Tür zu.'),
            ('auf / jeden Morgen / Meine Schwester / steht', 'Meine Schwester steht jeden Morgen auf.'),
            ('an / am Abend / Meine Eltern / rufen', 'Meine Eltern rufen am Abend an.'),
            ('auf / um sieben Uhr nach der Arbeit / Ich / stehe', 'Ich stehe um sieben Uhr nach der Arbeit auf.'),
            ('an / deine Mutter nach der Arbeit / Du / rufst', 'Du rufst deine Mutter nach der Arbeit an.'),
            ('ein / im Supermarkt nach der Arbeit / Er / kauft', 'Er kauft im Supermarkt nach der Arbeit ein.'),
            ('auf / das Zimmer nach der Arbeit / Sie / räumt', 'Sie räumt das Zimmer nach der Arbeit auf.'),
            ('an / um neun Uhr nach der Arbeit / Wir / fangen', 'Wir fangen um neun Uhr nach der Arbeit an.'),
            ('fern / am Abend nach der Arbeit / Ihr / seht', 'Ihr seht am Abend nach der Arbeit fern.'),
            ('zurück / morgen nach der Arbeit / Anna / kommt', 'Anna kommt morgen nach der Arbeit zurück.'),
            ('zu / die Tür nach der Arbeit / Paul / macht', 'Paul macht die Tür nach der Arbeit zu.'),
            ('auf / jeden Morgen nach der Arbeit / Meine Schwester / steht', 'Meine Schwester steht jeden Morgen nach der Arbeit auf.'),
            ('an / am Abend nach der Arbeit / Meine Eltern / rufen', 'Meine Eltern rufen am Abend nach der Arbeit an.'),
            ('auf / um sieben Uhr am Wochenende / Ich / stehe', 'Ich stehe um sieben Uhr am Wochenende auf.'),
            ('an / deine Mutter am Wochenende / Du / rufst', 'Du rufst deine Mutter am Wochenende an.'),
            ('ein / im Supermarkt am Wochenende / Er / kauft', 'Er kauft im Supermarkt am Wochenende ein.'),
            ('auf / das Zimmer am Wochenende / Sie / räumt', 'Sie räumt das Zimmer am Wochenende auf.'),
            ('an / um neun Uhr am Wochenende / Wir / fangen', 'Wir fangen um neun Uhr am Wochenende an.'),
            ('fern / am Abend am Wochenende / Ihr / seht', 'Ihr seht am Abend am Wochenende fern.'),
            ('zurück / morgen am Wochenende / Anna / kommt', 'Anna kommt morgen am Wochenende zurück.'),
            ('zu / die Tür am Wochenende / Paul / macht', 'Paul macht die Tür am Wochenende zu.'),
            ('auf / jeden Morgen am Wochenende / Meine Schwester / steht', 'Meine Schwester steht jeden Morgen am Wochenende auf.'),
            ('an / am Abend am Wochenende / Meine Eltern / rufen', 'Meine Eltern rufen am Abend am Wochenende an.'),
            ('auf / um sieben Uhr heute / Ich / stehe', 'Ich stehe um sieben Uhr heute auf.'),
            ('an / deine Mutter heute / Du / rufst', 'Du rufst deine Mutter heute an.'),
            ('ein / im Supermarkt heute / Er / kauft', 'Er kauft im Supermarkt heute ein.'),
            ('auf / das Zimmer heute / Sie / räumt', 'Sie räumt das Zimmer heute auf.'),
            ('an / um neun Uhr heute / Wir / fangen', 'Wir fangen um neun Uhr heute an.'),
            ('fern / am Abend heute / Ihr / seht', 'Ihr seht am Abend heute fern.'),
            ('zurück / morgen heute / Anna / kommt', 'Anna kommt morgen heute zurück.'),
            ('zu / die Tür heute / Paul / macht', 'Paul macht die Tür heute zu.'),
            ('auf / jeden Morgen heute / Meine Schwester / steht', 'Meine Schwester steht jeden Morgen heute auf.'),
            ('an / am Abend heute / Meine Eltern / rufen', 'Meine Eltern rufen am Abend heute an.'),
            ('auf / um sieben Uhr morgen / Ich / stehe', 'Ich stehe um sieben Uhr morgen auf.'),
            ('an / deine Mutter morgen / Du / rufst', 'Du rufst deine Mutter morgen an.'),
            ('ein / im Supermarkt morgen / Er / kauft', 'Er kauft im Supermarkt morgen ein.'),
            ('auf / das Zimmer morgen / Sie / räumt', 'Sie räumt das Zimmer morgen auf.'),
            ('an / um neun Uhr morgen / Wir / fangen', 'Wir fangen um neun Uhr morgen an.'),
            ('fern / am Abend morgen / Ihr / seht', 'Ihr seht am Abend morgen fern.'),
            ('zurück / morgen morgen / Anna / kommt', 'Anna kommt morgen morgen zurück.'),
            ('zu / die Tür morgen / Paul / macht', 'Paul macht die Tür morgen zu.'),
            ('auf / jeden Morgen morgen / Meine Schwester / steht', 'Meine Schwester steht jeden Morgen morgen auf.'),
            ('an / am Abend morgen / Meine Eltern / rufen', 'Meine Eltern rufen am Abend morgen an.'),
            ('gesehen / einen Film / Ich / habe / gestern', 'Ich habe gestern einen Film gesehen.'),
            ('getrunken / Kaffee / Du / hast / am Morgen', 'Du hast am Morgen Kaffee getrunken.'),
            ('gekauft / ein neues Buch / Er / hat / gestern', 'Er hat gestern ein neues Buch gekauft.'),
            ('gefahren / nach Zürich / Sie / ist / am Wochenende', 'Sie ist am Wochenende nach Zürich gefahren.'),
            ('gespielt / Fußball / Wir / haben / am Samstag', 'Wir haben am Samstag Fußball gespielt.'),
            ('gemacht / die Hausaufgaben / Ihr / habt / heute', 'Ihr habt heute die Hausaufgaben gemacht.'),
            ('aufgestanden / zu Hause / Anna / ist / früh', 'Anna ist früh zu Hause aufgestanden.'),
            ('angerufen / seine Freundin / Paul / hat / am Abend', 'Paul hat am Abend seine Freundin angerufen.'),
            ('geflogen / nach Berlin / Meine Eltern / sind / im Sommer', 'Meine Eltern sind im Sommer nach Berlin geflogen.'),
            ('gekocht / eine Suppe / Meine Schwester / hat / gestern', 'Meine Schwester hat gestern eine Suppe gekocht.'),
            ('gesehen / einen Film / mit Freunden / Ich / habe / gestern', 'Ich habe gestern mit Freunden einen Film gesehen.'),
            ('getrunken / Kaffee / mit Freunden / Du / hast / am Morgen', 'Du hast am Morgen mit Freunden Kaffee getrunken.'),
            ('gekauft / ein neues Buch / mit Freunden / Er / hat / gestern', 'Er hat gestern mit Freunden ein neues Buch gekauft.'),
            ('gefahren / nach Zürich / mit Freunden / Sie / ist / am Wochenende', 'Sie ist am Wochenende mit Freunden nach Zürich gefahren.'),
            ('gespielt / Fußball / mit Freunden / Wir / haben / am Samstag', 'Wir haben am Samstag mit Freunden Fußball gespielt.'),
            ('gemacht / die Hausaufgaben / mit Freunden / Ihr / habt / heute', 'Ihr habt heute mit Freunden die Hausaufgaben gemacht.'),
            ('aufgestanden / zu Hause / mit Freunden / Anna / ist / früh', 'Anna ist früh mit Freunden zu Hause aufgestanden.'),
            ('angerufen / seine Freundin / mit Freunden / Paul / hat / am Abend', 'Paul hat am Abend mit Freunden seine Freundin angerufen.'),
            ('geflogen / nach Berlin / mit Freunden / Meine Eltern / sind / im Sommer', 'Meine Eltern sind im Sommer mit Freunden nach Berlin geflogen.'),
            ('gekocht / eine Suppe / mit Freunden / Meine Schwester / hat / gestern', 'Meine Schwester hat gestern mit Freunden eine Suppe gekocht.'),
            ('gesehen / einen Film / zu Hause / Ich / habe / gestern', 'Ich habe gestern zu Hause einen Film gesehen.'),
            ('getrunken / Kaffee / zu Hause / Du / hast / am Morgen', 'Du hast am Morgen zu Hause Kaffee getrunken.'),
            ('gekauft / ein neues Buch / zu Hause / Er / hat / gestern', 'Er hat gestern zu Hause ein neues Buch gekauft.'),
            ('gefahren / nach Zürich / zu Hause / Sie / ist / am Wochenende', 'Sie ist am Wochenende zu Hause nach Zürich gefahren.'),
            ('gespielt / Fußball / zu Hause / Wir / haben / am Samstag', 'Wir haben am Samstag zu Hause Fußball gespielt.'),
            ('gemacht / die Hausaufgaben / zu Hause / Ihr / habt / heute', 'Ihr habt heute zu Hause die Hausaufgaben gemacht.'),
            ('aufgestanden / zu Hause / zu Hause / Anna / ist / früh', 'Anna ist früh zu Hause zu Hause aufgestanden.'),
            ('angerufen / seine Freundin / zu Hause / Paul / hat / am Abend', 'Paul hat am Abend zu Hause seine Freundin angerufen.'),
            ('geflogen / nach Berlin / zu Hause / Meine Eltern / sind / im Sommer', 'Meine Eltern sind im Sommer zu Hause nach Berlin geflogen.'),
            ('gekocht / eine Suppe / zu Hause / Meine Schwester / hat / gestern', 'Meine Schwester hat gestern zu Hause eine Suppe gekocht.'),
            ('gesehen / einen Film / in der Stadt / Ich / habe / gestern', 'Ich habe gestern in der Stadt einen Film gesehen.'),
            ('getrunken / Kaffee / in der Stadt / Du / hast / am Morgen', 'Du hast am Morgen in der Stadt Kaffee getrunken.'),
            ('gekauft / ein neues Buch / in der Stadt / Er / hat / gestern', 'Er hat gestern in der Stadt ein neues Buch gekauft.'),
            ('gefahren / nach Zürich / in der Stadt / Sie / ist / am Wochenende', 'Sie ist am Wochenende in der Stadt nach Zürich gefahren.'),
            ('gespielt / Fußball / in der Stadt / Wir / haben / am Samstag', 'Wir haben am Samstag in der Stadt Fußball gespielt.'),
            ('gemacht / die Hausaufgaben / in der Stadt / Ihr / habt / heute', 'Ihr habt heute in der Stadt die Hausaufgaben gemacht.'),
            ('aufgestanden / zu Hause / in der Stadt / Anna / ist / früh', 'Anna ist früh in der Stadt zu Hause aufgestanden.'),
            ('angerufen / seine Freundin / in der Stadt / Paul / hat / am Abend', 'Paul hat am Abend in der Stadt seine Freundin angerufen.'),
            ('geflogen / nach Berlin / in der Stadt / Meine Eltern / sind / im Sommer', 'Meine Eltern sind im Sommer in der Stadt nach Berlin geflogen.'),
            ('gekocht / eine Suppe / in der Stadt / Meine Schwester / hat / gestern', 'Meine Schwester hat gestern in der Stadt eine Suppe gekocht.'),
            ('gesehen / einen Film / am Abend / Ich / habe / gestern', 'Ich habe gestern am Abend einen Film gesehen.'),
            ('getrunken / Kaffee / am Abend / Du / hast / am Morgen', 'Du hast am Morgen am Abend Kaffee getrunken.'),
            ('gekauft / ein neues Buch / am Abend / Er / hat / gestern', 'Er hat gestern am Abend ein neues Buch gekauft.'),
            ('gefahren / nach Zürich / am Abend / Sie / ist / am Wochenende', 'Sie ist am Wochenende am Abend nach Zürich gefahren.'),
            ('gespielt / Fußball / am Abend / Wir / haben / am Samstag', 'Wir haben am Samstag am Abend Fußball gespielt.'),
            ('gemacht / die Hausaufgaben / am Abend / Ihr / habt / heute', 'Ihr habt heute am Abend die Hausaufgaben gemacht.'),
            ('aufgestanden / zu Hause / am Abend / Anna / ist / früh', 'Anna ist früh am Abend zu Hause aufgestanden.'),
            ('angerufen / seine Freundin / am Abend / Paul / hat / am Abend', 'Paul hat am Abend am Abend seine Freundin angerufen.'),
            ('geflogen / nach Berlin / am Abend / Meine Eltern / sind / im Sommer', 'Meine Eltern sind im Sommer am Abend nach Berlin geflogen.'),
            ('gekocht / eine Suppe / am Abend / Meine Schwester / hat / gestern', 'Meine Schwester hat gestern am Abend eine Suppe gekocht.'),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer = random.choice(exercises)
            qid = f"sentence|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "caption": "Ordena las palabras para formar una frase correcta.",
                "explanation": "Recuerda: el verbo conjugado ocupa normalmente la posición 2 en una oración principal.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "🧱 Satzbau",
            q["caption"],
            q["explanation"],
            "Frase completa",
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"sb_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 12 — NEBENSÄTZE
    # --------------------------------------------------------

    elif module == "Nebensätze":
        # Inicialización defensiva para evitar errores si esta versión de la app
        # se abre con una sesión creada por una versión anterior.
        if "last_message" not in st.session_state:
            st.session_state.last_message = {m: "" for m in MODULES}
        if "last_correct" not in st.session_state:
            st.session_state.last_correct = {m: None for m in MODULES}
        if module not in st.session_state.last_message:
            st.session_state.last_message[module] = ""
        if module not in st.session_state.last_correct:
            st.session_state.last_correct[module] = None

        st.subheader("🔗 Nebensätze")
        st.caption("Practica conectores, orden de palabras y posición del verbo en subordinadas.")

        exercises = [
            ("ordenar", "weil / ich / heute / arbeiten / muss", "weil ich heute arbeiten muss",
             ["weil ich muss heute arbeiten", "weil muss ich heute arbeiten"]),
            ("ordenar", "dass / er / morgen / kommt", "dass er morgen kommt",
             ["dass er kommt morgen", "dass kommt er morgen"]),
            ("ordenar", "wenn / ich / Zeit / habe", "wenn ich Zeit habe",
             ["wenn ich habe Zeit", "wenn habe ich Zeit"]),
            ("ordenar", "obwohl / es / regnet", "obwohl es regnet",
             ["obwohl regnet es", "obwohl es regnet ist"]),
            ("ordenar", "weil / wir / morgen / früh / aufstehen / müssen",
             "weil wir morgen früh aufstehen müssen",
             ["weil wir müssen morgen früh aufstehen", "weil müssen wir morgen früh aufstehen"]),
            ("ordenar", "dass / ich / Deutsch / lernen / möchte",
             "dass ich Deutsch lernen möchte",
             ["dass ich möchte Deutsch lernen", "dass möchte ich Deutsch lernen"]),
            ("estructura", "Ich bleibe zu Hause, weil ich heute ___ ___.", "arbeiten muss",
             ["muss arbeiten", "arbeite muss"]),
            ("estructura", "Ich weiß, dass er morgen ___ ___.", "kommen kann",
             ["kann kommen", "kommt kann"]),
            ("estructura", "Sie sagt, dass sie heute ___ ___.", "keine Zeit hat",
             ["hat keine Zeit", "keine Zeit haben"]),
            ("estructura", "Wir gehen spazieren, wenn das Wetter ___ ___.", "gut ist",
             ["ist gut", "gut sein"]),
            ("estructura", "Ich lerne Deutsch, weil ich in Deutschland ___ ___.",
             "arbeiten möchte", ["möchte arbeiten", "arbeite möchte"]),
            ("struktur", "Ich glaube, dass du das ___ ___.", "machen kannst",
             ["kannst machen", "machst kannst"]),
            ("konnektor", "Ich bleibe zu Hause, ___ ich krank bin.", "weil",
             ["obwohl", "dass"]),
            ("konnektor", "Ich hoffe, ___ du morgen kommst.", "dass",
             ["weil", "obwohl"]),
            ("konnektor", "___ ich Zeit habe, gehe ich ins Fitnessstudio.", "Wenn",
             ["Dass", "Weil"]),
            ("konnektor", "Ich gehe spazieren, ___ es regnet.", "obwohl",
             ["dass", "weil"]),
            ("konnektor", "___ ich ein Kind war, wohnte ich in Zürich.", "Als",
             ["Wenn", "Dass"]),
            ("vorangestellt", "Wenn ich Zeit habe, ___ ich meine Freunde.", "besuche",
             ["ich besuche", "besuchen"]),
            ("vorangestellt", "Weil ich krank bin, ___ ich heute zu Hause.", "bleibe",
             ["ich bleibe", "bleiben"]),
            ("vorangestellt", "Wenn das Wetter schön ist, ___ wir im Park.", "essen",
             ["wir essen", "essen wir"]),
            ("vorangestellt", "Obwohl es regnet, ___ ich spazieren.", "gehe",
             ["ich gehe", "gehen"]),
            ("vorangestellt", "Als ich klein war, ___ ich viel Fußball.", "spielte",
             ["ich spielte", "spielte ich"]),
            ("umstellen", "Weil ich müde bin, gehe ich früh ins Bett.",
             "Ich gehe früh ins Bett, weil ich müde bin.",
             ["Ich gehe früh ins Bett, weil bin ich müde.",
              "Ich gehe früh ins Bett, weil ich bin müde."]),
            ("umstellen", "Wenn ich Zeit habe, lese ich ein Buch.",
             "Ich lese ein Buch, wenn ich Zeit habe.",
             ["Ich lese ein Buch, wenn habe ich Zeit.",
              "Ich lese ein Buch, wenn ich habe Zeit."]),
            ("umstellen", "Obwohl es regnet, gehen wir spazieren.",
             "Wir gehen spazieren, obwohl es regnet.",
             ["Wir gehen spazieren, obwohl regnet es.",
              "Wir gehen spazieren, obwohl es regnet ist."]),
            ("fehler", "Ich bleibe zu Hause, weil ich bin krank.",
             "Ich bleibe zu Hause, weil ich krank bin.",
             ["Ich bleibe zu Hause, weil bin ich krank.",
              "Ich bleibe zu Hause, weil ich krank ist."]),
            ("fehler", "Wenn ich Zeit habe, ich gehe ins Kino.",
             "Wenn ich Zeit habe, gehe ich ins Kino.",
             ["Wenn ich Zeit habe, ich gehe ins Kino.",
              "Wenn ich habe Zeit, gehe ich ins Kino."]),
            ("fehler", "Ich glaube, dass er kommt morgen.",
             "Ich glaube, dass er morgen kommt.",
             ["Ich glaube, dass kommt er morgen.",
              "Ich glaube, dass er kommen morgen."]),
            ("fehler", "Sie bleibt zu Hause, weil sie ist müde.",
             "Sie bleibt zu Hause, weil sie müde ist.",
             ["Sie bleibt zu Hause, weil ist sie müde.",
              "Sie bleibt zu Hause, weil sie müde sein."]),
            ("fehler", "Obwohl es regnet, wir gehen spazieren.",
             "Obwohl es regnet, gehen wir spazieren.",
             ["Obwohl es regnet, wir spazieren gehen.",
              "Obwohl regnet es, gehen wir spazieren."]),
            ("fehler", "Ich weiß, dass du kannst kommen.",
             "Ich weiß, dass du kommen kannst.",
             ["Ich weiß, dass kannst du kommen.",
              "Ich weiß, dass du kannst kommen."]),
        ]

        # Variaciones adicionales para evitar un banco pequeño de preguntas.
        variations = [
            ("weil {s} heute zu Hause bleibt", "weil {s} heute zu Hause bleibt"),
            ("dass {s} morgen kommt", "dass {s} morgen kommt"),
            ("wenn {s} Zeit hat", "wenn {s} Zeit hat"),
            ("obwohl {s} müde ist", "obwohl {s} müde ist"),
        ]
        subjects = ["ich", "du", "er", "sie", "wir", "ihr"]
        for s in subjects:
            for left, right in variations:
                correct = right.format(s=s)
                wrong1 = correct.replace(f"{s} ", f"{s} ")
                parts = correct.split()
                if len(parts) >= 4:
                    wrong1 = " ".join(parts[:2] + parts[3:] + parts[2:3])
                wrong2 = " ".join(parts[:1] + parts[2:] + parts[1:2])
                exercises.append(("ordenar", " / ".join(correct.split()[1:]),
                                   correct, [wrong1, wrong2]))

        if st.session_state.questions[module] is None:
            recent = set(get_recent_question_ids(module, 30))
            candidates = [i for i in range(len(exercises)) if i not in recent] or list(range(len(exercises)))
            qid = random.choice(candidates)
            register_question(module, qid)
            st.session_state.questions[module] = {"id": qid, "data": exercises[qid]}

        q = st.session_state.questions[module]
        typ, prompt, correct, distractors = q["data"]

        # Pistas de vocabulario: el alumno nunca tiene que adivinar
        # qué verbo quería el ejercicio. La pista da los infinitivos /
        # palabras necesarias, pero no da la conjugación ni el orden final.
        hint = None

        def verb_hint_from_answer(answer):
            """
            Extrae pistas léxicas aproximadas de la respuesta correcta.
            No muestra formas conjugadas cuando puede inferir el infinitivo.
            """
            irregular = {
                "bin": "sein", "bist": "sein", "ist": "sein", "sind": "sein", "seid": "sein",
                "habe": "haben", "hast": "haben", "hat": "haben", "haben": "haben",
                "komme": "kommen", "kommst": "kommen", "kommt": "kommen",
                "gehe": "gehen", "gehst": "gehen", "geht": "gehen",
                "bleibe": "bleiben", "bleibst": "bleiben", "bleibt": "bleiben",
                "lerne": "lernen", "lernst": "lernen", "lernt": "lernen",
                "arbeite": "arbeiten", "arbeitest": "arbeiten", "arbeitet": "arbeiten",
                "wohne": "wohnen", "wohnst": "wohnen", "wohnt": "wohnen",
                "muss": "müssen", "musst": "müssen", "müssen": "müssen",
                "kann": "können", "kannst": "können", "können": "können",
                "möchte": "möchten", "möchtest": "möchten", "möchten": "möchten",
                "will": "wollen", "willst": "wollen", "wollen": "wollen",
                "soll": "sollen", "sollst": "sollen", "sollen": "sollen",
                "darf": "dürfen", "darfst": "dürfen", "dürfen": "dürfen",
                "kommt": "kommen", "geht": "gehen", "macht": "machen",
                "finde": "finden", "findest": "finden", "findet": "finden",
            }
            words = re.findall(r"[A-Za-zÄÖÜäöüß]+", answer)
            hints = []
            for w in words:
                low = w.lower()
                if low in irregular:
                    base = irregular[low]
                    if base not in hints:
                        hints.append(base)
            return hints

        if typ == "struktur":
            # Ej.: arbeiten möchte -> Verbos: arbeiten + möchten
            verbs = verb_hint_from_answer(correct)
            if verbs:
                hint = "💡 **Verben:** " + " + ".join(verbs)
            else:
                hint = "💡 **Pista:** usa el verbo indicado y conjúgalo según el sujeto."

        elif typ == "ordenar":
            # Si el conector no aparece en las palabras, se lo damos.
            connectors = ("obwohl", "wenn", "weil", "dass", "als")
            connector = next(
                (c for c in connectors if correct.lower().startswith(c + " ")),
                None
            )
            raw_words = prompt.lower().replace("/", " ").split()

            parts = []
            if connector and connector not in raw_words:
                parts.append(f"Conector: **{connector}**")

            verbs = verb_hint_from_answer(correct)
            if verbs:
                parts.append("Verbos: **" + " + ".join(verbs) + "**")

            if parts:
                hint = "💡 " + " · ".join(parts)
            else:
                hint = "💡 Ordena la frase y recuerda: el verbo conjugado va al final."

        elif typ == "konnektor":
            semantic_hints = {
                "weil": "causa / razón",
                "dass": "información / opinión",
                "wenn": "condición",
                "obwohl": "contraste",
                "als": "situación del pasado",
            }
            relation = semantic_hints.get(correct.lower(), "relación entre las dos partes")
            hint = f"💡 **Relación:** {relation}"

        elif typ == "vorangestellt":
            verbs = verb_hint_from_answer(correct)
            if verbs:
                hint = (
                    "💡 **Verbos:** " + " + ".join(verbs) +
                    " · Después de la coma: **verbo + sujeto**."
                )
            else:
                hint = "💡 Después de la coma: **verbo + sujeto**."

        elif typ == "umstellen":
            verbs = verb_hint_from_answer(correct)
            if verbs:
                hint = (
                    "💡 **Verbos:** " + " + ".join(verbs) +
                    " · Mantén el mismo significado."
                )
            else:
                hint = "💡 Mantén el mismo significado y conserva el verbo de la Nebensatz al final."

        elif typ == "fehler":
            verbs = verb_hint_from_answer(correct)
            if verbs:
                hint = (
                    "💡 **Verbos:** " + " + ".join(verbs) +
                    " · Busca el error en el orden/conjugación."
                )
            else:
                hint = "💡 Revisa la posición y conjugación del verbo."

        titles = {
            "ordenar": ("🧩 Ordena la subordinada",
                        "Ordena las palabras. El verbo conjugado va al final."),
            "estructura": ("🧩 Completa la estructura",
                          "Fíjate especialmente en la posición del verbo."),
            "struktur": ("🧩 Completa la estructura",
                         "Los verbos se colocan según la estructura de la Nebensatz."),
            "konnektor": ("🔗 Elige el conector",
                          "Piensa en causa, condición, información, tiempo o contraste."),
            "vorangestellt": ("↪️ Nebensatz al principio",
                              "Después de la coma viene el verbo de la Hauptsatz."),
            "umstellen": ("🔄 Cambia la posición",
                          "Mantén el significado y la estructura correcta."),
            "fehler": ("🔎 Corrige la estructura",
                       "Comprueba la posición del verbo y del sujeto."),
        }
        title, caption = titles[typ]
        st.markdown(f"### {title}")
        st.caption(caption)
        st.markdown(f"**{prompt}**")
        if hint:
            st.caption(hint)

        # En Nebensätze la respuesta se escribe: no mostramos alternativas.
        # Esto obliga a construir la estructura y practicar realmente el orden de palabras.
        choice = st.text_input(
            "Escribe la respuesta completa:",
            key=f"neb_input_{q['id']}",
            placeholder="Escribe aquí…",
        )

        if st.button("Comprobar", key=f"neb_check_{q['id']}"):
            ok = normalize(choice) == normalize(correct)
            mark_answer(module, prompt, st.session_state.level, choice, correct, ok)
            st.session_state.last_correct[module] = ok
            st.session_state.last_message[module] = (
                "✅ ¡Correcto!" if ok else f"❌ Incorrecto. La respuesta correcta es: **{correct}**"
            )
            st.rerun()

        if st.session_state.last_message[module]:
            st.info(st.session_state.last_message[module])
            if st.session_state.last_correct[module]:
                explanations = {
                    "ordenar": "En una Nebensatz con **weil, dass, wenn, obwohl, als**, el verbo conjugado va al final.",
                    "estructura": "En la subordinada, el verbo conjugado va al final; con un modal, el infinitivo va antes del modal.",
                    "struktur": "En una Nebensatz con modal, el infinitivo va antes y el verbo modal conjugado queda al final.",
                    "konnektor": "El conector determina la relación entre las dos partes de la frase.",
                    "vorangestellt": "Si la Nebensatz va primero: **Nebensatz, Verb + Subjekt + ...**.",
                    "umstellen": "La Nebensatz puede ir antes o después; su verbo mantiene la posición final.",
                    "fehler": "Hay que comprobar la posición final del verbo subordinado y la inversión de la Hauptsatz cuando la subordinada va primero.",
                }
                st.success(explanations[typ])
            if st.button("Siguiente", key=f"neb_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.last_message[module] = ""
                st.session_state.last_correct[module] = None
                st.rerun()

    elif module == "Präpositionen":

        exercises = [
            ("Ich fahre ___ Berlin.", "nach", ["nach", "in", "zu"]),
            ("Ich komme ___ der Schweiz.", "aus", ["aus", "von", "bei"]),
            ("Ich spreche ___ meinem Freund.", "mit", ["mit", "für", "bei"]),
            ("Das Geschenk ist ___ dich.", "für", ["für", "mit", "bei"]),
            ("Ich gehe ___ den Park.", "durch", ["durch", "für", "mit"]),
            ("Ich arbeite ___ einer Firma.", "bei", ["bei", "mit", "aus"]),
            ("Ich fahre ___ dem Zug.", "mit", ["mit", "in", "auf"]),
            ("Das ist ___ meinen Bruder.", "für", ["für", "mit", "zu"]),
            ("Wir gehen ___ das Haus.", "in", ["in", "an", "auf"]),
            ("Ich komme ___ dem Büro.", "aus", ["aus", "von", "zu"]),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer, options = random.choice(exercises)
            qid = f"prep|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "options": options,
                "caption": "Completa la preposición.",
                "explanation": "Preposiciones como mit, aus y bei rigen Dativ; für y durch rigen Akkusativ.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "📍 Präpositionen",
            q["caption"],
            q["explanation"],
            "Preposición",
            q["options"],
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"pp_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 14 — WO / WOHIN
    # --------------------------------------------------------

    elif module == "Wo / Wohin":

        exercises = [
            ("Ich gehe ___ Schule.", "in die", ["in die", "in der", "in den"]),
            ("Ich bin ___ Schule.", "in der", ["in der", "in die", "in den"]),
            ("Ich fahre ___ Supermarkt.", "in den", ["in den", "im", "in die"]),
            ("Ich bin ___ Supermarkt.", "im", ["im", "in den", "in der"]),
            ("Das Buch liegt ___ Tisch.", "auf dem", ["auf dem", "auf den", "in den"]),
            ("Ich lege das Buch ___ Tisch.", "auf den", ["auf den", "auf dem", "in dem"]),
            ("Ich gehe ___ Park.", "in den", ["in den", "im", "in die"]),
            ("Ich bin ___ Park.", "im", ["im", "in den", "in der"]),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer, options = random.choice(exercises)
            qid = f"wohin|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "options": options,
                "caption": "Lugar fijo → Dativ. Movimiento/dirección → Akkusativ.",
                "explanation": "Compara: Ich bin im Park. / Ich gehe in den Park.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "🚶 Wo / Wohin",
            q["caption"],
            q["explanation"],
            "Completa",
            q["options"],
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"ww_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 15 — PRONOMEN
    # --------------------------------------------------------

    elif module == "Pronomen":

        exercises = [
            ("Ich sehe ___ jeden Tag. (er)", "ihn", ["ihn", "ihm", "er"]),
            ("Ich helfe ___. (er)", "ihm", ["ihm", "ihn", "er"]),
            ("Sie sieht ___. (ich)", "mich", ["mich", "mir", "ich"]),
            ("Er gibt ___ das Buch. (ich)", "mir", ["mir", "mich", "ich"]),
            ("Wir besuchen ___. (sie)", "sie", ["sie", "ihr", "ihnen"]),
            ("Sie hilft ___. (wir)", "uns", ["uns", "wir", "unser"]),
            ("Ich kenne ___. (du)", "dich", ["dich", "dir", "du"]),
            ("Ich spreche mit ___. (du)", "dir", ["dir", "dich", "du"]),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer, options = random.choice(exercises)
            qid = f"pronomen|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "options": options,
                "caption": "Elige la forma correcta de Akkusativ o Dativ.",
                "explanation": "mich/dich/ihn/sie/es son Akkusativ; mir/dir/ihm/ihr/uns/euch/ihnen son Dativ.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "👤 Pronomen",
            q["caption"],
            q["explanation"],
            "Pronombre",
            q["options"],
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"pro_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 16 — POSSESSIVARTIKEL
    # --------------------------------------------------------

    elif module == "Possessivartikel":

        exercises = [
            ("Das ist ___ Bruder. (ich)", "mein", ["mein", "meinen", "meinem"]),
            ("Ich sehe ___ Bruder. (ich)", "meinen", ["meinen", "mein", "meinem"]),
            ("Ich spreche mit ___ Bruder. (ich)", "meinem", ["meinem", "mein", "meinen"]),
            ("Das ist ___ Schwester. (ich)", "meine", ["meine", "meiner", "meinen"]),
            ("Ich helfe ___ Schwester. (ich)", "meiner", ["meiner", "meine", "meinen"]),
            ("Das ist ___ Auto. (du)", "dein", ["dein", "deinem", "deinen"]),
            ("Ich fahre mit ___ Auto. (du)", "deinem", ["deinem", "dein", "deinen"]),
            ("Ich sehe ___ Freunde. (wir)", "unsere", ["unsere", "unser", "unseren"]),
            ("Das ist ___ Haus. (sie)", "ihr", ["ihr", "ihre", "ihrem"]),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer, options = random.choice(exercises)
            qid = f"possessiv|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "options": options,
                "caption": "Practica mein, dein, sein, ihr, unser, etc. con los casos.",
                "explanation": "El posesivo se declina como un artículo indefinido: mein → meinen → meinem.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "🏠 Possessivartikel",
            q["caption"],
            q["explanation"],
            "Possessivartikel",
            q["options"],
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"po_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 17 — KOMPARATIV
    # --------------------------------------------------------

    elif module == "Komparativ":
        # Inicialización defensiva: esta versión puede abrirse con una sesión
        # creada por una versión anterior de la aplicación.
        if "last_message" not in st.session_state:
            st.session_state.last_message = {m: "" for m in MODULES}
        if "last_correct" not in st.session_state:
            st.session_state.last_correct = {m: None for m in MODULES}
        if module not in st.session_state.last_message:
            st.session_state.last_message[module] = ""
        if module not in st.session_state.last_correct:
            st.session_state.last_correct[module] = None

        st.subheader("📈 Komparativ")
        st.caption("Escribe la forma comparativa correcta del adjetivo.")

        # Banco variado de ejercicios originales A1-A2.
        comparative_data = [
            ("Berlin ist ___ als Zürich. (alt)", "älter"),
            ("Mein Bruder ist ___ als ich. (groß)", "größer"),
            ("Der Zug ist ___ als der Bus. (schnell)", "schneller"),
            ("Heute ist es ___ als gestern. (warm)", "wärmer"),
            ("Diese Aufgabe ist ___ als die letzte. (leicht)", "leichter"),
            ("Deutsch ist für mich ___ als Englisch. (schwierig)", "schwieriger"),
            ("Das neue Auto ist ___ als das alte. (modern)", "moderner"),
            ("Meine Wohnung ist ___ als deine. (klein)", "kleiner"),
            ("Der Sommer ist ___ als der Winter. (heiß)", "heißer"),
            ("Der Winter ist ___ als der Herbst. (kalt)", "kälter"),
            ("Ein Fahrrad ist ___ als ein Auto. (billig)", "billiger"),
            ("Ein Taxi ist ___ als ein Bus. (teuer)", "teurer"),
            ("Heute bin ich ___ als gestern. (müde)", "müder"),
            ("Maria läuft ___ als Peter. (schnell)", "schneller"),
            ("Dieses Restaurant ist ___ als das andere. (gut)", "besser"),
            ("Der Film war ___ als das Buch. (schlecht)", "schlechter"),
            ("Mein Kaffee ist ___ als deiner. (stark)", "stärker"),
            ("Die neue Wohnung ist ___ als die alte. (schön)", "schöner"),
            ("Der Weg zur Arbeit ist ___ als früher. (kurz)", "kürzer"),
            ("Meine Arbeit ist ___ als mein Studium. (interessant)", "interessanter"),
            ("Ein Elefant ist ___ als ein Hund. (schwer)", "schwerer"),
            ("Ein Hund ist ___ als eine Maus. (groß)", "größer"),
            ("Der Zug fährt ___ als das Auto. (langsam)", "langsamer"),
            ("Diese Tasche ist ___ als meine alte Tasche. (praktisch)", "praktischer"),
            ("Der rote Pullover ist ___ als der blaue. (teuer)", "teurer"),
            ("Im Sommer sind die Tage ___. (lang)", "länger"),
            ("Im Winter sind die Nächte ___. (lang)", "länger"),
            ("Mein neuer Computer ist ___ als mein alter. (schnell)", "schneller"),
            ("Dieses Hotel ist ___ als das Hotel am Bahnhof. (ruhig)", "ruhiger"),
            ("Der Morgen ist ___ als der Abend. (hell)", "heller"),
            ("Die Prüfung war ___ als erwartet. (schwer)", "schwerer"),
            ("Meine Schwester ist ___ als mein Bruder. (jung)", "jünger"),
            ("Der Bahnhof ist ___ als der Flughafen. (nah)", "näher"),
            ("Diese Straße ist ___ als die andere. (breit)", "breiter"),
            ("Der neue Tisch ist ___ als der alte. (stabil)", "stabiler"),
            ("Das Fahrrad ist ___ als das Motorrad. (umweltfreundlich)", "umweltfreundlicher"),
            ("Heute habe ich ___ Zeit als gestern. (viel)", "mehr"),
            ("Ich habe heute ___ Geld als letzte Woche. (wenig)", "weniger"),
            ("Dieses Buch kostet ___ als das andere. (viel)", "mehr"),
            ("Der zweite Film war ___ als der erste. (spannend)", "spannender"),
            ("Die Aufgabe ist ___ als sie aussieht. (einfach)", "einfacher"),
            ("Mein Weg zur Schule ist ___ als deiner. (weit)", "weiter"),
            ("Der Supermarkt ist ___ als die Bäckerei. (weit)", "weiter"),
            ("Diese Schuhe sind ___ als meine alten. (bequem)", "bequemer"),
            ("Das Zimmer ist ___ als die Küche. (groß)", "größer"),
            ("Die Küche ist ___ als das Wohnzimmer. (klein)", "kleiner"),
            ("Der Arztbesuch war ___ als erwartet. (kurz)", "kürzer"),
            ("Heute fühle ich mich ___ als gestern. (gut)", "besser"),
            ("Nach dem Urlaub bin ich ___ als vorher. (entspannt)", "entspannter"),
            ("Der Kaffee schmeckt ___ als der Tee. (gut)", "besser"),
            ("Das Wetter ist heute ___ als am Montag. (schlecht)", "schlechter"),
            ("Meine neue Jacke ist ___ als meine alte. (warm)", "wärmer"),
            ("Der Weg mit dem Fahrrad ist ___ als mit dem Auto. (schnell)", "schneller"),
            ("Diese Übung ist ___ als die vorige. (nützlich)", "nützlicher"),
            ("Der Park ist ___ als die Straße. (ruhig)", "ruhiger"),
            ("Das Meer ist ___ als der See. (groß)", "größer"),
            ("Ein See ist ___ als ein Meer. (klein)", "kleiner"),
            ("Mein Koffer ist ___ als deiner. (schwer)", "schwerer"),
            ("Diese Aufgabe braucht ___ Zeit als die erste. (viel)", "mehr"),
            ("Ich trinke heute ___ Kaffee als gestern. (wenig)", "weniger"),
            ("Der Weg ist ___ als gedacht. (lang)", "länger"),
            ("Die Stadt ist am Wochenende ___ als unter der Woche. (ruhig)", "ruhiger"),
            ("Das Zentrum ist ___ als mein Wohnviertel. (laut)", "lauter"),
            ("Mein Arbeitsplatz ist ___ als früher. (hell)", "heller"),
            ("Der neue Bildschirm ist ___ als der alte. (groß)", "größer"),
            ("Diese App ist ___ als die alte Version. (einfach)", "einfacher"),
            ("Das Hotelzimmer ist ___ als auf den Fotos. (klein)", "kleiner"),
            ("Der Flug ist ___ als die Zugfahrt. (kurz)", "kürzer"),
            ("Die Zugfahrt ist ___ als der Flug. (lang)", "länger"),
            ("Meine Deutschkenntnisse sind ___ als letztes Jahr. (gut)", "besser"),
            ("Ich verstehe die Grammatik jetzt ___. (gut)", "besser"),
            ("Diese Erklärung ist ___ als die vorige. (klar)", "klarer"),
            ("Der Lehrer spricht ___ als vorher. (langsam)", "langsamer"),
            ("Meine Aussprache ist ___ als vor einem Monat. (gut)", "besser"),
            ("Der neue Kurs ist ___ als der alte. (interessant)", "interessanter"),
            ("Die zweite Lektion ist ___ als die erste. (kurz)", "kürzer"),
            ("Diese Regel ist ___ als die andere. (wichtig)", "wichtiger"),
            ("Das Beispiel ist ___ als die Erklärung. (einfach)", "einfacher"),
            ("Der Test war ___ als die Hausaufgabe. (schwer)", "schwerer"),
            ("Mein Deutschbuch ist ___ als mein Englischbuch. (dick)", "dicker"),
            ("Der rote Stift ist ___ als der blaue. (dünn)", "dünner"),
            ("Diese Flasche ist ___ als die andere. (leicht)", "leichter"),
            ("Der Koffer ist ___ als die Tasche. (schwer)", "schwerer"),
            ("Das Fahrrad ist ___ als der Roller. (schnell)", "schneller"),
            ("Der Roller ist ___ als das Fahrrad. (langsam)", "langsamer"),
            ("Der Weg nach Hause ist ___ als der Weg zur Arbeit. (kurz)", "kürzer"),
            ("Am Wochenende schlafe ich ___. (lang)", "länger"),
            ("Im Urlaub stehe ich ___ auf als normalerweise. (spät)", "später"),
            ("Heute bin ich ___ aufgestanden als gestern. (früh)", "früher"),
            ("Der zweite Bus kommt ___ als der erste. (spät)", "später"),
            ("Der erste Zug fährt ___ als der zweite. (früh)", "früher"),
            ("Diese Lösung ist ___ als die andere. (gut)", "besser"),
            ("Der neue Plan ist ___ als der alte. (realistisch)", "realistischer"),
            ("Das Gespräch war ___ als erwartet. (interessant)", "interessanter"),
            ("Der neue Job ist ___ als mein alter. (flexibel)", "flexibler"),
            ("Die Arbeitszeiten sind ___ als früher. (flexibel)", "flexibler"),
            ("Diese Wohnung ist ___ als meine vorige. (teuer)", "teurer"),
            ("Dafür ist sie ___ als meine vorige. (groß)", "größer"),
            ("Das Essen hier ist ___ als zu Hause. (teuer)", "teurer"),
            ("Aber es schmeckt ___. (gut)", "besser"),
            ("Der Markt ist ___ als der Supermarkt. (klein)", "kleiner"),
            ("Die Preise dort sind ___. (niedrig)", "niedriger"),
            ("Der Laden ist ___ als das Einkaufszentrum. (nah)", "näher"),
            ("Das Einkaufszentrum ist ___ als der Laden. (weit)", "weiter"),
            ("Diese Hose ist ___ als meine Jeans. (bequem)", "bequemer"),
            ("Die Jeans ist ___ als die Hose. (praktisch)", "praktischer"),
            ("Das Wetter in Zürich ist heute ___ als in Bern. (warm)", "wärmer"),
            ("Bern ist im Sommer oft ___ als Zürich. (ruhig)", "ruhiger"),
            ("Der See ist im Frühling ___ als im Winter. (warm)", "wärmer"),
            ("Die Berge sind ___ als die Hügel. (hoch)", "höher"),
            ("Der Berg ist ___ als der Hügel. (hoch)", "höher"),
            ("Das Tal ist ___ als der Berg. (tief)", "tiefer"),
            ("Die Stadt ist ___ als das Dorf. (groß)", "größer"),
            ("Das Dorf ist ___ als die Stadt. (klein)", "kleiner"),
            ("Das Dorf ist ___ als die Stadt. (ruhig)", "ruhiger"),
            ("Die Stadt ist ___ als das Dorf. (laut)", "lauter"),
            ("Ein Zug ist ___ als ein Fahrrad. (schnell)", "schneller"),
            ("Ein Fahrrad ist ___ als ein Zug. (langsam)", "langsamer"),
            ("Das Flugzeug ist ___ als der Zug. (schnell)", "schneller"),
            ("Der Zug ist ___ als das Flugzeug. (langsam)", "langsamer"),
            ("Diese Sprache ist ___ als ich dachte. (schwierig)", "schwieriger"),
            ("Die Aussprache ist ___ als die Grammatik. (schwierig)", "schwieriger"),
            ("Der Text ist ___ als der vorige. (lang)", "länger"),
            ("Der Dialog ist ___ als der Text. (kurz)", "kürzer"),
            ("Diese Frage ist ___ als die vorige. (leicht)", "leichter"),
            ("Die letzte Frage war ___. (schwer)", "schwerer"),
            ("Heute lerne ich ___ als gestern. (viel)", "mehr"),
            ("Heute mache ich ___ Fehler als früher. (wenig)", "weniger"),
            ("Jetzt verstehe ich ___ als am Anfang. (viel)", "mehr"),
            ("Ich habe jetzt ___ Probleme als vorher. (wenig)", "weniger"),
            ("Meine Antwort ist ___ als vorher. (gut)", "besser"),
            ("Meine Sätze sind ___ als früher. (lang)", "länger"),
            ("Ich spreche jetzt ___ als früher. (sicher)", "sicherer"),
            ("Ich fühle mich beim Sprechen ___. (sicher)", "sicherer"),
            ("Die neue Lektion ist ___ als die alte. (interessant)", "interessanter"),
            ("Der neue Wortschatz ist ___ als der vorige. (nützlich)", "nützlicher"),
            ("Diese Methode ist ___ als die alte. (effektiv)", "effektiver"),
            ("Der neue Test ist ___ als der letzte. (schwer)", "schwerer"),
            ("Die heutige Aufgabe ist ___ als gestern. (einfach)", "einfacher"),
            ("Das neue Beispiel ist ___ als das alte. (verständlich)", "verständlicher"),
        ]

        # Shuffle deterministic only through Python's random state; avoid immediate repeats.
        if st.session_state.questions[module] is None:
            recent = set(get_recent_question_ids(module, 30))
            candidates = [i for i in range(len(comparative_data)) if i not in recent]
            if not candidates:
                candidates = list(range(len(comparative_data)))
            qid = random.choice(candidates)
            register_question(module, qid)
            st.session_state.questions[module] = {
                "id": qid,
                "prompt": comparative_data[qid][0],
                "correct": comparative_data[qid][1],
            }

        q = st.session_state.questions[module]

        st.markdown("### 📈 Komparativ")
        st.caption("Escribe la forma comparativa del adjetivo entre paréntesis.")
        st.markdown(f"**{q['prompt']}**")

        user = st.text_input(
            "Respuesta:",
            key=f"komp_input_{q['id']}",
            placeholder="Escribe el comparativo…",
        )

        if st.button("Comprobar", key=f"komp_check_{q['id']}"):
            ok = normalize(user) == normalize(q["correct"])
            mark_answer(
                module,
                q["prompt"],
                st.session_state.level,
                user,
                q["correct"],
                ok,
            )
            st.session_state.last_correct[module] = ok
            st.session_state.last_message[module] = (
                "✅ ¡Correcto!"
                if ok
                else f"❌ Incorrecto. La respuesta correcta es: **{q['correct']}**"
            )
            st.rerun()

        if st.session_state.last_message[module]:
            st.info(st.session_state.last_message[module])
            if st.session_state.last_correct[module]:
                st.success(
                    "El Komparativ normalmente se forma con **-er**. "
                    "Algunos adjetivos cambian la vocal: **alt → älter, "
                    "jung → jünger, groß → größer, gut → besser, "
                    "viel → mehr, wenig → weniger**."
                )
            if st.button("Siguiente", key=f"komp_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.last_message[module] = ""
                st.session_state.last_correct[module] = None
                st.rerun()

    elif module == "Adverbien":

        exercises = [
            ("Ich gehe ___ ins Fitnessstudio. (often)", "oft"),
            ("Ich trinke ___ Kaffee. (always)", "immer"),
            ("Ich komme ___ zu spät. (never)", "nie"),
            ("Ich arbeite ___ am Wochenende. (sometimes)", "manchmal"),
            ("Ich bin ___ zu Hause. (usually)", "meistens"),
            ("Ich habe ___ keine Zeit. (still)", "noch"),
            ("Ich bin ___ fertig. (already)", "schon"),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer = random.choice(exercises)
            qid = f"adverb|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "caption": "Completa con el adverbio de frecuencia o tiempo.",
                "explanation": "Estos adverbios son muy frecuentes en la conversación diaria.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "🔄 Adverbien",
            q["caption"],
            q["explanation"],
            "Adverbio",
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"ad_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 19 — NICHT / KEIN
    # --------------------------------------------------------

    elif module == "Nicht / Kein":

        exercises = [
            ("Ich habe ___ Auto.", "kein"),
            ("Ich habe ___ Zeit.", "keine"),
            ("Das ist ___ gut.", "nicht"),
            ("Ich komme heute ___.", "nicht"),
            ("Wir haben ___ Kinder.", "keine"),
            ("Er ist ___ müde.", "nicht"),
            ("Das ist ___ Problem.", "kein"),
            ("Sie trinkt ___ Kaffee.", "keinen"),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer = random.choice(exercises)
            qid = f"negation|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "caption": "Decide entre nicht y kein.",
                "explanation": "kein niega sustantivos; nicht se usa para negar verbos, adjetivos, adverbios o la oración.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "🚫 Nicht / Kein",
            q["caption"],
            q["explanation"],
            "Completa",
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"nk_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 20 — FRAGEN
    # --------------------------------------------------------

    elif module == "Fragen":

        exercises = [
            ("___ kommst du?", "Woher"),
            ("___ wohnst du?", "Wo"),
            ("___ gehst du morgen?", "Wohin"),
            ("___ arbeitest du?", "Wo"),
            ("___ lernst du Deutsch?", "Warum"),
            ("___ beginnt der Kurs?", "Wann"),
            ("___ kostet das?", "Wie viel"),
            ("___ dauert der Kurs?", "Wie lange"),
        ]

        if st.session_state.questions[module] is None:
            prompt, answer = random.choice(exercises)
            qid = f"frage|{prompt}"
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "prompt": prompt,
                "correct": answer,
                "caption": "Completa la W-Frage.",
                "explanation": "Practica wo, wohin, woher, wann, warum, wie lange y wie viel.",
            }

        q = st.session_state.questions[module]

        simple_question(
            q["id"],
            q["prompt"],
            q["correct"],
            "❓ Fragen",
            q["caption"],
            q["explanation"],
            "W-Frage",
        )

        if st.session_state.answered[module]:
            if st.button("➡️ Siguiente", key=f"fr_next_{q['id']}"):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 21 — LÜCKENTEXT
    # --------------------------------------------------------

    elif module == "Lückentext":

        texts = [
            {
                "text": "Gestern ___ ich mit meiner Freundin nach Berlin ___.",
                "answers": ["bin", "gefahren"],
            },
            {
                "text": "Am Samstag ___ ich keine Zeit, weil ich arbeiten ___.",
                "answers": ["hatte", "musste"],
            },
            {
                "text": "Ich bleibe zu Hause, weil ich krank ___.",
                "answers": ["bin"],
            },
            {
                "text": "Morgen ___ ich mit dem Zug nach München ___.",
                "answers": ["fahre", "fahren"],
            },
        ]

        if st.session_state.questions[module] is None:
            item = random.choice(texts)
            qid = "lueckentext|" + item["text"]
            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "text": item["text"],
                "answers": item["answers"],
            }

        q = st.session_state.questions[module]

        st.subheader("📖 Lückentext")
        st.caption(
            "Completa todos los huecos."
        )

        st.markdown(
            f'<div class="case_sentence">{q["text"]}</div>',
            unsafe_allow_html=True,
        )

        answers = []

        cols = st.columns(
            len(q["answers"])
        )

        for index, col in enumerate(cols):
            with col:
                answers.append(
                    st.text_input(
                        f"Hueco {index + 1}",
                        key=f"luecke_{q['id']}_{index}",
                    )
                )

        if st.button(
            "Comprobar",
            key=f"check_luecke_{q['id']}",
        ):
            ok = all(
                normalize(answers[i])
                == normalize(q["answers"][i])
                for i in range(len(q["answers"]))
            )

            mark_answer(
                module,
                q["text"],
                st.session_state.level,
                " | ".join(answers),
                " | ".join(q["answers"]),
                ok,
            )

            st.rerun()

        if st.session_state.answered[module]:

            if st.session_state.last_correct[module]:
                st.success("✅ ¡Todo correcto!")
            else:
                st.error(
                    "❌ Hay uno o más huecos incorrectos."
                )

            st.info(
                "Solución: "
                + " · ".join(q["answers"])
            )

            if st.button(
                "➡️ Siguiente",
                key=f"next_luecke_{q['id']}",
            ):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()

    # --------------------------------------------------------
    # 22 — LESEN
    # --------------------------------------------------------

    elif module == "Lesen":

        readings = [
            {
                "text": (
                    "Anna arbeitet in einem Büro in Zürich. "
                    "Sie beginnt jeden Morgen um acht Uhr. "
                    "Am Montag fährt sie mit dem Zug zur Arbeit. "
                    "Nach der Arbeit trifft sie manchmal ihre Freundin "
                    "in einem Café."
                ),
                "questions": [
                    ("Wo arbeitet Anna?", "in einem Büro", ["in einem Büro", "in einem Café", "am Bahnhof"]),
                    ("Wann beginnt sie?", "um acht Uhr", ["um acht Uhr", "um sieben Uhr", "um neun Uhr"]),
                    ("Wie fährt sie zur Arbeit?", "mit dem Zug", ["mit dem Zug", "mit dem Auto", "mit dem Bus"]),
                ],
            },
            {
                "text": (
                    "Paul hat am Wochenende Besuch von seinem Bruder. "
                    "Am Samstag gehen sie zuerst einkaufen. "
                    "Danach kochen sie zusammen. "
                    "Am Abend sehen sie einen Film."
                ),
                "questions": [
                    ("Wer besucht Paul?", "sein Bruder", ["sein Bruder", "seine Schwester", "sein Freund"]),
                    ("Was machen sie danach?", "Sie kochen zusammen.", ["Sie kochen zusammen.", "Sie gehen spazieren.", "Sie lernen zusammen."]),
                    ("Was machen sie am Abend?", "Sie sehen einen Film.", ["Sie sehen einen Film.", "Sie lesen ein Buch.", "Sie gehen ins Café."]),
                ],
            },
        ]

        if st.session_state.questions[module] is None:

            reading = random.choice(readings)
            question, answer, options = random.choice(
                reading["questions"]
            )

            qid = (
                f"lesen|{question}|"
                f"{reading['text']}"
            )

            register_question(module, qid)

            st.session_state.questions[module] = {
                "id": qid,
                "text": reading["text"],
                "question": question,
                "correct": answer,
                "options": options,
            }

        q = st.session_state.questions[module]

        st.subheader("📄 Lesen")

        st.markdown(
            f'<div class="case_sentence">'
            f'{q["text"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f"**Pregunta:** {q['question']}"
        )

        user = st.radio(
            "Elige la respuesta correcta:",
            q["options"],
            key=f"lesen_{q['id']}",
        )

        if st.button(
            "Comprobar",
            key=f"check_lesen_{q['id']}",
            use_container_width=True,
        ):
            expected = normalize(q["correct"])
            given = normalize(user)
            ok = given == expected

            mark_answer(
                module,
                q["question"],
                st.session_state.level,
                user,
                q["correct"],
                ok,
            )

            st.rerun()

        if st.session_state.answered[module]:

            if st.session_state.last_correct[module]:
                st.success("✅ ¡Correcto!")
            else:
                st.error(
                    f"❌ Una respuesta válida sería: "
                    f"**{q['correct']}**"
                )

            if st.button(
                "➡️ Siguiente",
                key=f"lesen_next_{q['id']}",
            ):
                st.session_state.questions[module] = None
                st.session_state.answered[module] = False
                st.session_state.last_correct[module] = None
                st.rerun()


# ============================================================
# INFORMACIÓN
# ============================================================

st.sidebar.markdown("---")

st.sidebar.caption(
    "Las preguntas recientes se registran en SQLite "
    "para reducir repeticiones."
)
