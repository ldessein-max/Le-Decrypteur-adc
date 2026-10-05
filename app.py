import os
import re
import unicodedata
import requests
import pdfplumber
import streamlit as st

# ==========================================
# CONFIGURATION & PAGE SETUP
# ==========================================
st.set_page_config(
    page_title="Le Décrypteur ADC",
    page_icon="🔍",
    layout="wide"
)

# Récupération des secrets
DOMAIN = st.secrets.get("SYNCHROTEAM_DOMAIN", "")
API_KEY = st.secrets.get("SYNCHROTEAM_API_KEY", "")

# Authentification minimale pour l'application
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

def login():
    st.sidebar.title("Connexion")
    password = st.sidebar.text_input("Mot de passe", type="password")
    if st.sidebar.button("Se connecter"):
        if password == "adc2024":  # À personnaliser si besoin
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.sidebar.error("Mot de passe incorrect")

if not st.session_state["authenticated"]:
    login()
    st.stop()

# ==========================================
# FONCTIONS API SYNCHROTEAM
# ==========================================
HEADERS = {
    "Authorization": f"Basic {API_KEY}",
    "Content-Type": "application/json"
}

def build_url(endpoint):
    return f"https://{DOMAIN}.synchroteam.com/api/v3{endpoint}"

def normalize_string(s):
    if not s:
        return ""
    s = unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode("utf-8")
    return re.sub(r'[^a-zA-Z0-9]', '', s).lower()

def safe_post(url, payload):
    try:
        response = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        return response
    except Exception as e:
        st.error(f"Erreur réseau API : {e}")
        return None

def get_or_create_customer(pdf_client_name):
    clean_client_name = pdf_client_name.strip()
    
    # 1. Recherche par nom
    try:
        res_search = requests.get(
            build_url(f"/customer/list?name={requests.utils.quote(clean_client_name)}"),
            headers=HEADERS,
            timeout=10
        )
        if res_search.status_code == 200:
            data = res_search.json()
            clients = data.get("data", []) if isinstance(data, dict) else data
            for c in clients:
                if normalize_string(c.get("name", "")) == normalize_string(clean_client_name):
                    return c.get("id")
                if normalize_string(clean_client_name) in normalize_string(c.get("name", "")):
                    return c.get("id")
    except Exception:
        pass

    # 2. Création si absent
    clean_myid = "CLI-" + re.sub(r"[^A-Za-z0-9]", "", clean_client_name).upper()[:10]
    payload = {
        "name": clean_client_name,
        "myId": clean_myid,
        "address": "À renseigner",
        "city": "Paris",
        "zipCode": "75000",
        "country": "France"
    }
    
    res_create = safe_post(build_url("/customer/send"), payload)
    if res_create and res_create.status_code in [200, 201]:
        return res_create.json().get("id")
    return None

def create_site_in_synchroteam(customer_id, site_info):
    payload = {
        "customerId": customer_id,
        "name": site_info.get("name", "Nouveau Site"),
        "myId": site_info.get("myid", ""),
        "address": site_info.get("address", ""),
        "zipCode": site_info.get("zip", ""),
        "city": site_info.get("city", ""),
        "country": "France"
    }
    res = safe_post(build_url("/site/send"), payload)
    if res and res.status_code in [200, 201]:
        return res.json().get("id")
    return None

# ==========================================
# PARSER PDF DU BON DE COMMANDE
# ==========================================
def parse_pdf_file(uploaded_file):
    site_info = {
        "client": "",
        "name": "",
        "myid": "",
        "address": "",
        "zip": "",
        "city": "",
        "measures": []
    }
    
    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"

        # 1. Extraction Client (Arrêt strict au retour à la ligne)
        client_m = re.search(r"CLIENT\s*:\s*([^\n]+)", full_text, re.IGNORECASE)
        if client_m:
            site_info["client"] = client_m.group(1).strip()

        # 2. Extraction Dossier et Référence
        dossier_m = re.search(r"DOSSIER\s*N°\s*:\s*([^\n(]+)\s*\(([^)]+)\)", full_text, re.IGNORECASE)
        if dossier_m:
            site_info["name"] = dossier_m.group(1).strip()
            site_info["myid"] = dossier_m.group(2).strip()
        else:
            simple_dossier = re.search(r"DOSSIER\s*N°\s*:\s*([^\n]+)", full_text, re.IGNORECASE)
            if simple_dossier:
                site_info["name"] = simple_dossier.group(1).strip()

        # 3. Extraction Adresse d'intervention multi-lignes
        adresse_m = re.search(
            r"ADRESSE D'INTERVENTION\s*:\s*([\s\S]+?)(?=\n\n|\n[A-Z\s]{4,}:|BON DE COMMANDE|$)",
            full_text,
            re.IGNORECASE
        )
        if adresse_m:
            raw_addr_block = adresse_m.group(1).strip()
            clean_addr_full = re.sub(r"\s+", " ", raw_addr_block).strip()
            
            cp_ville_m = re.search(r"(\d{5})\s+(.+)", clean_addr_full)
            if cp_ville_m:
                site_info["zip"] = cp_ville_m.group(1)
                site_info["city"] = cp_ville_m.group(2).strip()
                street_m = re.search(r"^(.*?)\s*\d{5}", clean_addr_full)
                site_info["address"] = street_m.group(1).strip() if street_m and street_m.group(1).strip() else clean_addr_full
            else:
                site_info["address"] = clean_addr_full

        # 4. Extraction de la section "Bon de Commande" pour les prestations
        bdc_marker = re.search(r"BON DE COMMANDE", full_text, re.IGNORECASE)
        if bdc_marker:
            bdc_text = full_text[bdc_marker.start():]
            for line in bdc_text.split("\n"):
                if re.search(r"\b(Prélèvement|Mesurage|Analyse|Diagnostic|Comptage)\b", line, re.IGNORECASE):
                    site_info["measures"].append(line.strip())

    return site_info

# ==========================================
# INTERFACE STREAMLIT
# ==========================================
st.title("📄 Le Décrypteur ADC")

tab_import, tab_history = st.tabs(["🚀 Importation", "📜 Historique"])

with tab_import:
    uploaded_files = st.file_uploader("Fichiers PDF", type=["pdf"], accept_multiple_files=True)
    
    if uploaded_files and st.button(f"Lancer ({len(uploaded_files)})"):
        for file in uploaded_files:
            st.write(f"---")
            info = parse_pdf_file(file)
            
            st.write(f"📄 **Fichier :** `{file.name}`")
            st.write(f"🏢 **Client capturé :** `{info['client']}`")
            st.write(f"📍 **Dossier :** `{info['name']}` (Réf: `{info['myid']}`)")
            st.write(f"🏠 **Adresse :** {info['address']} | {info['zip']} {info['city']}")
            
            if info["client"]:
                customer_id = get_or_create_customer(info["client"])
                if customer_id:
                    site_id = create_site_in_synchroteam(customer_id, info)
                    if site_id:
                        st.success(f"Site créé avec succès dans Synchroteam (ID: {site_id}) !")
                    else:
                        st.error("Échec lors de la création du site.")
                else:
                    st.error("Échec lors de la création/récupération du client.")
            else:
                st.warning("Aucun nom de client capturé dans le document.")
