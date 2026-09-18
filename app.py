import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


# ============================================================
# CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Deutsch Lernen",
    page_icon="🇩🇪",
    layout="centered",
)

BASE_DIR = Path(__file__).parent
CSV_FILE = BASE_DIR / "data" / "vocabulary.csv"
DB_FILE = BASE_DIR / "progress.db"


# ============================================================
# BASE DE DATOS
# ============================================================

conn = sqlite3.connect(DB_FILE, check_same_thread=False)

conn.execute(
    """
    CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT NOT NULL,
        level TEXT NOT NULL,
        module TEXT NOT NULL,
        selected TEXT,
        expected TEXT,
        correct INTEGER NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
)

conn.commit()


# ============================================================
# VOCABULARIO
# ============================================================

@st.cache_data
def load_vocabulary():

    df = pd.read_csv(CSV_FILE).fillna("")

    df["has_article"] = (
        df["has_article"]
        .astype(str)
        .str.lower()
        .isin(["true", "1", "yes"])
    )

    return df


vocab = load_vocabulary()


# ============================================================
# FUNCIONES
# ============================================================

def save_answer(
    word,
    level,
    module,
    selected,
    expected,
    correct,
):

    conn.execute(
        """
        INSERT INTO answers
        (
            word,
            level,
            module,
            selected,
            expected,
            correct
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            word,
            level,
            module,
            selected,
            expected,
            int(correct),
        ),
    )

    conn.commit()


def get_history():

    return pd.read_sql_query(
        """
        SELECT *
        FROM answers
        ORDER BY id DESC
        """,
        conn,
    )


def choose_word(df):

    if len(df) == 0:
        return None

    return df.sample(1).iloc[0].to_dict()


def reset_question(df):

    st.session_state.current_word = choose_word(df)

    st.session_state.answered = False
    st.session_state.last_correct = None
    st.session_state.last_answer = None


def normalize(text):

    return str(text).lower().strip()


# ============================================================
# SESSION STATE
# ============================================================

defaults = {

    "module": "Artículos",

    "level": "Todos",

    "current_word": None,

    "answered": False,

    "last_correct": None,

    "last_answer": None,

    "score": 0,

    "total": 0,

}


for key, value in defaults.items():

    if key not in st.session_state:

        st.session_state[key] = value


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("🇩🇪 Deutsch Lernen")


st.sidebar.selectbox(
    "Nivel",
    [
        "Todos",
        "A1",
        "A2",
        "B1",
    ],
    key="level",
)


st.sidebar.radio(
    "Módulo",
    [
        "Artículos",
        "Vocabulario",
        "Plurales",
    ],
    key="module",
)


# ============================================================
# FILTRAR NIVEL
# ============================================================

if st.session_state.level == "Todos":

    filtered = vocab.copy()

else:

    filtered = vocab[
        vocab["level"]
        == st.session_state.level
    ].copy()


# ============================================================
# MÓDULO 1 — ARTÍCULOS
# ============================================================

if st.session_state.module == "Artículos":

    st.title("🧠 Der, die oder das?")

    st.write(
        "Selecciona el artículo correcto."
    )


    article_words = filtered[
        filtered["has_article"]
    ].copy()


    if article_words.empty:

        st.warning(
            "No hay sustantivos disponibles "
            "para este nivel."
        )

        st.stop()


    available_words = set(
        article_words["word"]
    )


    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word["word"]
        not in available_words
    ):

        reset_question(article_words)


    word = st.session_state.current_word


    st.markdown(
        f"""
        <div style="
            text-align:center;
            font-size:52px;
            font-weight:700;
            margin:50px 0;
        ">
            {word["word"]}
        </div>
        """,
        unsafe_allow_html=True,
    )


    col1, col2, col3 = st.columns(3)


    for col, article in zip(
        [col1, col2, col3],
        ["der", "die", "das"],
    ):

        with col:

            if st.button(
                article.upper(),
                use_container_width=True,
                disabled=st.session_state.answered,
            ):

                correct = (
                    word["article"]
                    == article
                )

                st.session_state.total += 1

                if correct:
                    st.session_state.score += 1

                st.session_state.answered = True

                st.session_state.last_answer = article

                st.session_state.last_correct = correct


                save_answer(
                    word["word"],
                    word["level"],
                    "articles",
                    article,
                    word["article"],
                    correct,
                )

                st.rerun()


    if st.session_state.answered:

        if st.session_state.last_correct:

            st.success(
                "✅ ¡Correcto!"
            )

        else:

            st.error(
                f"❌ Incorrecto. "
                f"La respuesta era "
                f"**{word['article']} "
                f"{word['word']}**."
            )


        st.info(
            f"🇪🇸 {word['translation']}"
        )


        if word["plural"]:

            st.write(
                f"🔤 Plural: "
                f"**die {word['plural']}**"
            )


        st.write(
            f"📝 **{word['example_de']}**"
        )

        st.caption(
            word["example_es"]
        )


        if st.button(
            "➡️ Siguiente palabra",
            use_container_width=True,
        ):

            reset_question(article_words)

            st.rerun()


# ============================================================
# MÓDULO 2 — VOCABULARIO
# ============================================================

elif st.session_state.module == "Vocabulario":

    st.title("📚 Vocabulario")

    st.write(
        "Practica alemán ↔ español."
    )


    mode = st.radio(
        "Modo",

        [
            "Alemán → español",
            "Español → alemán",
        ],

        horizontal=True,
    )


    available_words = set(
        filtered["word"]
    )


    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word["word"]
        not in available_words
    ):

        reset_question(filtered)


    word = st.session_state.current_word


    if word["article"]:

        german_display = (
            f"{word['article']} "
            f"{word['word']}"
        )

    else:

        german_display = word["word"]


    if mode == "Alemán → español":

        st.markdown(
            f"""
            <div style="
                text-align:center;
                font-size:45px;
                font-weight:700;
                margin:50px 0;
            ">
                {german_display}
            </div>
            """,
            unsafe_allow_html=True,
        )


        answer = st.text_input(
            "Escribe la traducción:",
            key="translation_input",
            disabled=st.session_state.answered,
        )


        if st.button(
            "Comprobar",
            use_container_width=True,
            disabled=st.session_state.answered,
        ):

            expected = normalize(
                word["translation"]
            )

            selected = normalize(answer)

            correct = (
                selected == expected
            )


            st.session_state.total += 1


            if correct:
                st.session_state.score += 1


            st.session_state.answered = True

            st.session_state.last_correct = correct

            st.session_state.last_answer = answer


            save_answer(
                word["word"],
                word["level"],
                "vocabulary",
                answer,
                word["translation"],
                correct,
            )


            st.rerun()


    else:

        st.markdown(
            f"""
            <div style="
                text-align:center;
                font-size:42px;
                font-weight:700;
                margin:50px 0;
            ">
                {word["translation"]}
            </div>
            """,
            unsafe_allow_html=True,
        )


        answer = st.text_input(
            "Escribe la palabra alemana:",
            key="german_input",
            disabled=st.session_state.answered,
        )


        if st.button(
            "Comprobar",
            use_container_width=True,
            disabled=st.session_state.answered,
        ):

            expected = normalize(
                german_display
            )

            selected = normalize(answer)

            correct = (
                selected == expected
            )


            st.session_state.total += 1


            if correct:
                st.session_state.score += 1


            st.session_state.answered = True

            st.session_state.last_correct = correct

            st.session_state.last_answer = answer


            save_answer(
                word["word"],
                word["level"],
                "vocabulary",
                answer,
                german_display,
                correct,
            )


            st.rerun()


    if st.session_state.answered:

        if st.session_state.last_correct:

            st.success(
                "✅ ¡Correcto!"
            )

        else:

            st.error(
                "❌ Incorrecto."
            )

            st.info(
                f"Respuesta correcta: "
                f"**{german_display}**"
                if mode == "Español → alemán"
                else
                f"Respuesta correcta: "
                f"**{word['translation']}**"
            )


        st.write(
            f"📝 **{word['example_de']}**"
        )

        st.caption(
            word["example_es"]
        )


        if st.button(
            "➡️ Siguiente",
            use_container_width=True,
        ):

            reset_question(filtered)

            st.rerun()


# ============================================================
# MÓDULO 3 — PLURALES
# ============================================================

else:

    st.title("🔤 Módulo 3 — Plurales")

    st.write(
        "Escribe el plural correcto de la palabra."
    )


    # Solo palabras que tienen plural
    plural_words = filtered[
        filtered["plural"].astype(str).str.strip() != ""
    ].copy()


    if plural_words.empty:

        st.warning(
            "No hay palabras con plural "
            "disponibles para este nivel."
        )

        st.stop()


    available_words = set(
        plural_words["word"]
    )


    if (
        st.session_state.current_word is None
        or
        st.session_state.current_word["word"]
        not in available_words
    ):

        reset_question(plural_words)


    word = st.session_state.current_word


    # --------------------------------------------------------
    # PALABRA
    # --------------------------------------------------------

    if word["article"]:

        singular = (
            f"{word['article']} "
            f"{word['word']}"
        )

    else:

        singular = word["word"]


    st.markdown(
        f"""
        <div style="
            text-align:center;
            font-size:48px;
            font-weight:700;
            margin:45px 0 15px 0;
        ">
            {singular}
        </div>
        """,
        unsafe_allow_html=True,
    )


    st.markdown(
        f"""
        <div style="
            text-align:center;
            font-size:20px;
            margin-bottom:35px;
        ">
            🇪🇸 {word["translation"]}
        </div>
        """,
        unsafe_allow_html=True,
    )


    # --------------------------------------------------------
    # INPUT
    # --------------------------------------------------------

    answer = st.text_input(
        "Escribe el plural:",
        placeholder="Ejemplo: Tische",
        key="plural_input",
        disabled=st.session_state.answered,
    )


    if st.button(
        "Comprobar",
        use_container_width=True,
        disabled=st.session_state.answered,
    ):

        expected = normalize(
            word["plural"]
        )

        selected = normalize(
            answer
        )

        correct = (
            selected == expected
        )


        st.session_state.total += 1


        if correct:

            st.session_state.score += 1


        st.session_state.answered = True

        st.session_state.last_correct = correct

        st.session_state.last_answer = answer


        save_answer(
            word["word"],
            word["level"],
            "plurals",
            answer,
            word["plural"],
            correct,
        )


        st.rerun()


    # --------------------------------------------------------
    # FEEDBACK
    # --------------------------------------------------------

    if st.session_state.answered:

        if st.session_state.last_correct:

            st.success(
                "✅ ¡Correcto!"
            )

        else:

            st.error(
                f"❌ Incorrecto."
            )

            st.info(
                f"El plural correcto es: "
                f"**die {word['plural']}**"
            )


        st.write(
            f"📝 **{word['example_de']}**"
        )

        st.caption(
            word["example_es"]
        )


        if st.button(
            "➡️ Siguiente palabra",
            use_container_width=True,
        ):

            reset_question(
                plural_words
            )

            st.rerun()


# ============================================================
# ESTADÍSTICAS
# ============================================================

st.divider()

st.subheader(
    "📊 Tu progreso"
)


col1, col2, col3 = st.columns(3)


col1.metric(
    "Aciertos",
    st.session_state.score,
)


col2.metric(
    "Intentos",
    st.session_state.total,
)


if st.session_state.total:

    accuracy = (
        st.session_state.score
        / st.session_state.total
        * 100
    )

else:

    accuracy = 0


col3.metric(
    "Precisión",
    f"{accuracy:.0f}%",
)


st.progress(
    accuracy / 100
)


# ============================================================
# PALABRAS DÉBILES
# ============================================================

history = get_history()


if not history.empty:

    st.divider()

    st.subheader(
        "🎯 Palabras que necesitas practicar"
    )


    statistics = (
        history
        .groupby(
            ["word", "level", "module"]
        )
        .agg(
            intentos=("correct", "count"),
            aciertos=("correct", "sum"),
        )
        .reset_index()
    )


    statistics["precision"] = (
        statistics["aciertos"]
        / statistics["intentos"]
        * 100
    ).round(0)


    weak_words = (
        statistics
        .sort_values(
            ["precision", "intentos"]
        )
        .head(10)
    )


    st.dataframe(
        weak_words[
            [
                "word",
                "level",
                "module",
                "intentos",
                "aciertos",
                "precision",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )


# ============================================================
# HISTORIAL
# ============================================================

if not history.empty:

    st.subheader(
        "📝 Últimos ejercicios"
    )


    recent = history.head(10).copy()


    recent["Resultado"] = (
        recent["correct"]
        .map(
            {
                1: "✅",
                0: "❌",
            }
        )
    )


    st.dataframe(
        recent[
            [
                "word",
                "level",
                "module",
                "selected",
                "expected",
                "Resultado",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )


# ============================================================
# SIDEBAR — CONTROLES
# ============================================================

st.sidebar.divider()


if st.sidebar.button(
    "🔄 Reiniciar sesión"
):

    st.session_state.score = 0
    st.session_state.total = 0
    st.session_state.current_word = None
    st.session_state.answered = False
    st.session_state.last_correct = None
    st.session_state.last_answer = None

    st.rerun()


if st.sidebar.button(
    "🗑️ Borrar historial"
):

    conn.execute(
        "DELETE FROM answers"
    )

    conn.commit()

    st.session_state.score = 0
    st.session_state.total = 0

    st.success(
        "Historial eliminado."
    )

    st.rerun()