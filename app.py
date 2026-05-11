import streamlit as st
import os
import logging
import time
import requests as req

from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools import tool
from agno.db.sqlite import SqliteDb

from dotenv import load_dotenv

import folium
from streamlit_folium import st_folium

# ===================== SETUP =====================
os.makedirs("tmp", exist_ok=True)
load_dotenv()
logging.basicConfig(level=logging.INFO)

CITY = "Purbalingga"

# ===================== HELPER =====================
@st.cache_data(ttl=3600)
def get_coordinates(nama_tempat: str):
    if not nama_tempat.strip():
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{nama_tempat} {CITY}", "format": "json", "limit": 1}
    headers = {"User-Agent": os.getenv("APP_NAME", "plesiran-app")}

    for _ in range(3):
        try:
            resp = req.get(url, params=params, headers=headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            return {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
        except Exception as e:
            logging.warning(f"Gagal ambil koordinat: {e}")
            time.sleep(1)

    return None


def render_map(p, key):
    m = folium.Map(location=[p["lat"], p["lon"]], zoom_start=16)
    folium.Marker(
        [p["lat"], p["lon"]],
        popup=p["nama"],
        tooltip=p["nama"],
        icon=folium.Icon(color="red", icon="info-sign"),
    ).add_to(m)
    st_folium(m, height=300, use_container_width=True, key=key)


@st.cache_data(ttl=1800)
def fetch_weather(kota: str = "Purbalingga") -> dict | None:
    """Ambil data cuaca dari OpenWeatherMap, cache 30 menit."""
    try:
        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            return None
        resp = req.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": f"{kota},ID", "appid": api_key, "units": "metric", "lang": "id"},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.warning(f"fetch_weather error: {e}")
        return None


def render_weather_widget(kota: str = "Purbalingga"):
    """Tampilkan widget cuaca mini di sidebar."""
    data = fetch_weather(kota)
    if not data:
        st.sidebar.caption("⚠️ Cuaca tidak tersedia")
        return

    desc    = data["weather"][0]["description"].capitalize()
    suhu    = data["main"]["temp"]
    feels   = data["main"]["feels_like"]
    hum     = data["main"]["humidity"]
    icon_id = data["weather"][0]["icon"]
    icon_url = f"https://openweathermap.org/img/wn/{icon_id}@2x.png"

    # Map kondisi ke emoji
    main = data["weather"][0]["main"].lower()
    emoji = {"clear": "☀️", "clouds": "☁️", "rain": "🌧️",
             "drizzle": "🌦️", "thunderstorm": "⛈️", "snow": "❄️", "mist": "🌫️"}.get(main, "🌤️")

    with st.sidebar.container(border=True):
        st.markdown(f"<center><b>🌤️ Cuaca {kota}</b></center>", unsafe_allow_html=True)
        col_icon, col_info= st.columns([1, 2])
        with col_icon:
            st.image(icon_url, width=60)
        with col_info:
            st.markdown(f"**{emoji} {suhu:.0f}°C**")
            st.caption(f"{desc}")
        st.caption(f"🌡️ Terasa {feels:.0f}°C &nbsp;&nbsp; 💧 {hum}%")


# ===================== TOOLS =====================
@tool(name="web_search")
def web_search(query: str) -> str:
    """
    Cari informasi terkini dari internet.
    Gunakan untuk mencari harga tiket, jam buka, alamat, hotel, dan fakta spesifik.
    """
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append(f"- {r['title']}: {r['body']}")
        return "\n".join(results) if results else "Tidak ada hasil ditemukan."
    except Exception as e:
        logging.error(f"web_search error: {e}")
        return f"Gagal melakukan pencarian: {str(e)}"


@tool
def show_map(nama_tempat: str) -> str:
    """Tampilkan peta lokasi wisata berdasarkan nama tempat."""
    coords = get_coordinates(nama_tempat)
    if not coords:
        return f"Koordinat {nama_tempat} tidak ditemukan."
    st.session_state.peta = {"nama": nama_tempat, **coords}
    return f"Koordinat ditemukan: {coords['lat']}, {coords['lon']}"


@tool(name="get_weather")
def get_weather(kota: str = "Purbalingga") -> str:
    """
    Ambil info cuaca terkini suatu kota.
    Gunakan saat user tanya cuaca atau meminta itinerary wisata.
    """
    data = fetch_weather(kota)
    if not data:
        return "Gagal ambil data cuaca."
    return (
        f"Cuaca {kota}: {data['weather'][0]['description']}, "
        f"suhu {data['main']['temp']}°C "
        f"(terasa {data['main']['feels_like']}°C), "
        f"kelembaban {data['main']['humidity']}%, "
        f"angin {data['wind']['speed']} m/s."
    )


@tool(name="get_route")
def get_route(asal: str, tujuan: str) -> str:
    """
    Hitung jarak dan estimasi waktu tempuh antara dua tempat wisata di Purbalingga.
    Gunakan saat user minta itinerary atau tanya jarak antar tempat.
    """
    try:
        coords_asal   = get_coordinates(asal)
        coords_tujuan = get_coordinates(tujuan)

        if not coords_asal:
            return f"Koordinat '{asal}' tidak ditemukan."
        if not coords_tujuan:
            return f"Koordinat '{tujuan}' tidak ditemukan."

        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{coords_asal['lon']},{coords_asal['lat']};"
            f"{coords_tujuan['lon']},{coords_tujuan['lat']}"
            f"?overview=false"
        )
        resp = req.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            return f"Rute dari {asal} ke {tujuan} tidak ditemukan."

        route = data["routes"][0]
        return (
            f"Rute {asal} → {tujuan}: "
            f"jarak {round(route['distance'] / 1000, 1)} km, "
            f"estimasi {round(route['duration'] / 60)} menit berkendara."
        )
    except Exception as e:
        logging.error(f"get_route error: {e}")
        return f"Gagal ambil data rute: {str(e)}"


# ===================== AGENT =====================
def get_agent():
    if "agent" not in st.session_state:
        st.session_state.agent = Agent(
            model=Groq(id="llama-3.1-8b-instant"),
            db=SqliteDb(db_file="tmp/data.db"),
            description="Kamu adalah tour guide profesional wisata dan kuliner Purbalingga.",
            instructions=[
                "Kamu tour guide Purbalingga yang ramah.",
                "Wajib gunakan tool web_search sebelum menjawab fakta spesifik (harga, jam, alamat, hotel).",
                "Gunakan get_weather saat user tanya cuaca atau minta itinerary.",
                "Gunakan get_route saat user minta itinerary atau tanya jarak/waktu tempuh antar tempat.",
                "Saat membuat itinerary: gunakan get_weather untuk kondisi cuaca, get_route untuk jarak antar destinasi, web_search untuk harga tiket dan rekomendasi hotel.",
                "Jawab dalam bahasa Indonesia secara natural, maksimal 3 bullet points kecuali untuk itinerary.",
                "Untuk itinerary, tampilkan dalam format tabel: Waktu | Destinasi | Durasi | Jarak dari titik sebelumnya.",
                "Tanpa heading, kode, atau tag. Bold hanya nama tempat dan angka penting.",
                "Jangan tulis atau tampilkan function call; panggil tool secara internal.",
                "Panggil show_map hanya jika user minta 'peta' atau 'maps'.",
                "Setelah show_map dipanggil, beri tahu bahwa peta sudah muncul di bawah.",
                "Jika user minta peta tanpa menyebut nama tempat, gunakan nama tempat yang paling terakhir dibahas dalam percakapan.",
                "Sertakan disclaimer bahwa harga bersifat estimasi dan perlu dikonfirmasi langsung.",
            ],
            tools=[web_search, show_map, get_weather, get_route],
            add_history_to_context=True,
            num_history_runs=3,
            markdown=True,
        )
    return st.session_state.agent


# ===================== UI =====================
st.set_page_config(page_title="Plesiran", page_icon="⛰️", layout="wide")

with st.sidebar:
    # Logo
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("plesiran.png", use_container_width=True)

    # Widget cuaca di bawah logo
    render_weather_widget()

    st.markdown("---")

    # Destinasi Populer
    container = st.container(border=True)
    container.markdown("<center><b>Destinasi Populer</b></center>", unsafe_allow_html=True)

    destinasi = {
        "-- Pilih Destinasi --": None,
        "🏖️ Owabong Waterpark": "Jelaskan tentang Owabong Waterpark secara lengkap",
        "🎠 Purbasari Pancuran Mas": "Jelaskan tentang Purbasari Pancuran Mas secara lengkap",
        "🦚 Sanggaluri Park": "Jelaskan tentang Sanggaluri Park secara lengkap",
        "🦇 Gua Lawa": "Jelaskan tentang Gua Lawa Purbalingga secara lengkap",
        "🌊 Curug Ciputut": "Jelaskan tentang Curug Ciputut Purbalingga secara lengkap",
        "🌿 Curug Nini": "Jelaskan tentang Curug Nini Purbalingga secara lengkap",
        "🏔️ Bukit Sipetung": "Jelaskan tentang Bukit Sipetung Purbalingga secara lengkap",
        "🎭 Museum Wayang Sendang Mas": "Jelaskan tentang Museum Wayang Sendang Mas Purbalingga secara lengkap",
        "🕌 Masjid Agung Purbalingga": "Jelaskan tentang Masjid Agung Purbalingga secara lengkap",
        "🏛️ Pendopo Dipokusumo": "Jelaskan tentang Pendopo Dipokusumo Purbalingga secara lengkap",
    }

    pilihan = container.selectbox(
        label="destinasi",
        options=list(destinasi.keys()),
        label_visibility="collapsed",
        key="pilihan_destinasi",
    )

    st.markdown("---")

    # Itinerary Generator
    itinerary_container = st.container(border=True)
    itinerary_container.markdown("<center><b>🗓️ Buat Itinerary</b></center>", unsafe_allow_html=True)

    durasi = itinerary_container.radio(
        "Durasi wisata:",
        ["1 Hari", "2 Hari", "3 Hari (Weekend++)"],
        horizontal=False,
        key="durasi_itinerary",
    )

    jumlah_orang = itinerary_container.number_input(
        "Jumlah orang:",
        min_value=1,
        max_value=20,
        value=2,
        key="jumlah_orang",
    )

    buat_itinerary = itinerary_container.button("✨ Generate Itinerary", use_container_width=True)

    

    if st.button("🔄 Reset Chat", use_container_width=True, type="secondary"):
        st.session_state.messages = []
        st.session_state.peta = None
        if "agent" in st.session_state:
            del st.session_state["agent"]
        st.rerun()
        
    
    st.markdown("---")
    st.markdown(
        "<center><sub>Dibuat dengan 💡 oleh Adi Setiawan</sub></center>",
        unsafe_allow_html=True,
    )

# ===================== SIDEBAR PROMPT =====================
sidebar_prompt = destinasi.get(pilihan)

if buat_itinerary:
    hari = durasi.split()[0]
    sidebar_prompt = (
        f"Buatkan itinerary wisata Purbalingga untuk {hari} hari "
        f"dengan {jumlah_orang} orang. "
        f"Gunakan get_weather untuk cek cuaca, get_route untuk jarak antar destinasi, "
        f"dan web_search untuk harga tiket serta rekomendasi hotel. "
        f"Tampilkan jadwal per hari dalam tabel (Waktu | Destinasi | Durasi | Jarak dari titik sebelumnya), "
        f"lalu buat estimasi budget breakdown (tiket, makan, hotel, transport) untuk {jumlah_orang} orang. "
        f"Sertakan disclaimer harga bersifat estimasi."
    )

# ===================== CHAT =====================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "peta" not in st.session_state:
    st.session_state.peta = None

st.title("⛰️ Plesiran")
st.markdown("Selamat Datang di **Purbalingga Travel Assistant**")

if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown("Halo! Ada yang bisa saya bantu hari ini tentang wisata atau kuliner Purbalingga?")

# Tampilkan history
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
    if msg.get("peta"):
        render_map(msg["peta"], key=f"peta_{i}")

# Input
user_input = st.chat_input("Tanyakan tentang wisata Purbalingga...")
active_prompt = user_input if user_input else sidebar_prompt

# ===================== RUN =====================
if active_prompt:
    st.session_state.pop("peta", None)

    # Reset dropdown agar tidak trigger ulang saat rerun
    if not user_input and sidebar_prompt:
        # st.session_state.pilihan_destinasi = "-- Pilih Destinasi --"
        st.session_state["_sidebar_used"] = True

    st.session_state.messages.append({"role": "user", "content": active_prompt})

    with st.chat_message("user"):
        st.markdown(active_prompt)

    agent = get_agent()

    with st.chat_message("assistant"), st.spinner("Mencari info wisata & lokasi..."):
        try:
            response = agent.run(active_prompt, stream=False)
            answer = response.content
        except Exception as e:
            logging.error(f"Agent error: {e}")
            answer = "Maaf, ada kendala teknis. Silakan coba lagi."

        st.markdown(answer)

    # Peta di luar chat bubble
    peta_now = st.session_state.get("peta")
    if peta_now:
        render_map(peta_now, key=f"peta_{len(st.session_state.messages)}")

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "peta": peta_now,
    })
