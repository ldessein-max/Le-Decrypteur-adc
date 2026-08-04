import re
import streamlit as st
import requests
import pdfplumber

# 1. Configuration de la page
st.set_page_config(
    page_title="Le Décrypteur ADC", 
    page_icon="🦛", 
    layout="centered"
)

# 2. Injection CSS pour le design moderne (Correction du paramètre unsafe_allow_html)
st.markdown("""
    <style>
    /* Fond principal de l'application */
    .stApp {
        background-color: #F8F9FA;
    }
    
    /* Cartes personnalisées */
    .custom-card {
        background-color: #FFFFFF;
        padding: 2rem;
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        border-left: 6px solid #8DB600;
        margin-bottom: 1.5rem;
    }
    
    .login-card {
        background-color: #FFFFFF;
        padding: 2.5rem;
        border-radius: 16px;
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
        border-top: 6px solid #004B87;
        text-align: center;
    }

    /* Titres et textes */
    h1, h2, h3 {
        color: #004B87 !important;
        font-weight: 700 !important;
    }
    
    /* Style du bouton principal */
    .stButton>button {
        background-color: #004B87 !important;
        color: white !important;
        border-radius: 8px !important;
        border: none !important;
        padding: 0.6rem 1.2rem !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
        width: 100%;
    }
    
    .stButton>button:hover {
        background-color: #8DB600 !important;
        color: white !important;
        transform: translateY(-2px);
    }
    
    /* Zone de file uploader */
    [data-testid="stFileUploader"] {
        background-color: #FFFFFF;
        border-radius: 12px;
        padding: 1rem;
        border: 2px dashed #004B87;
    }
    </style>
""", unsafe_allow_html=True)

# 3. Authentification obligatoire (@adc-labo.fr)
def check_email():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
        st.session_state["user_email"] = ""

    if not st.session_state["authenticated"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown('<div class="login-card">', unsafe_allow_html=True)
            try:
                st.image("ACD_WEB_RVB.png", use_container_width=True)
            except Exception:
                st.title("A.D.C")
            
            st.markdown("### **Portail d'accès**")
            st.caption("Analyses - Diagnostics - Contrôles")
            st.write("---")
            
            email_input = st.text_input("Adresse e-mail professionnelle :", placeholder="exemple@adc-labo.fr")
            
            if st.button("Se connecter 🚀"):
                email_clean = email_input.strip().lower()
                email_pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
                
                if not email_clean:
                    st.error("Veuillez renseigner une adresse e-mail.")
                elif not re.match(email_pattern, email_clean):
                    st.error("Format d'adresse e-mail invalide.")
                elif not email_clean.endswith("@adc-labo.fr"):
                    st.error("Accès réservé exclusivement aux adresses @adc-labo.fr")
                else:
                    st.session_state["authenticated"] = True
                    st.session_state["user_email"] = email_clean
                    st.rerun()
            
            st.markdown('</div>', unsafe_allow_html=True)
        return False
    return True

# 4. Application Principale
if check_email():

    # Barre latérale (Sidebar) pour le profil et la déconnexion
    with st.sidebar:
        try:
            st.image("ACD_WEB_RVB.png", use_container_width=True)
        except Exception:
            pass
        st.write("---")
        st.markdown(f"👤 **Utilisateur :**\n`{st.session_state['user_email']}`")
        if st.button("Se déconnecter"):
            st.session_state["authenticated"] = False
            st.session_state["user_email"] = ""
            st.rerun()

    # En-tête de page
    col_title, col_logo = st.columns([3, 1])

    with col_title:
        st.title("Le Décrypteur ADC")
        st.caption("Génération automatisée des interventions Synchroteam")

    with col_logo:
        try:
            st.image("ACD_WEB_RVB.png", use_container_width=True)
        except Exception:
            st.caption("[Logo ADC Labo]")

    st.write("---")

    # Configuration API Synchroteam
    DOMAIN = st.secrets.get("SYNCHROTEAM_DOMAIN", "mon-domaine")
    API_KEY = st.secrets.get("SYNCHROTEAM_API_KEY", "ma-cle-api")
    BASE_URL = f"https://{DOMAIN}.synchroteam.com/api/v3"
    AUTH = (DOMAIN, API_KEY)

    # Fonctions Utilitaires
    def extract_text_from_pdf(uploaded_file):
        text = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        return text

    @st.cache_data(ttl=3600)
    def get_all_job_types():
        job_types = {}
        page = 1
        while True:
            url = f"{BASE_URL}/job/types?page={page}"
            response = requests.get(url, auth=AUTH)
            if response.status_code != 200:
                break
            data = response.json()
            items = data.get("categoryList", []) or data.get("jobTypeList", []) or data
            if isinstance(data, dict) and "data" in data:
                items = data["data"]
            
            if not items:
                break
                
            for item in items:
                name = item.get("name") or item.get("label")
                id_val = item.get("id")
                if name and id_val:
                    job_types[name.strip().lower()] = id_val
                    
            if len(items) < 25:
                break
            page += 1
        return job_types

    # Zone de dépôt du PDF
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📄 Dépôt du rapport PDF")
    uploaded_file = st.file_uploader("Glissez-déposez votre stratégie PDF ci-dessous :", type=["pdf"])
    st.markdown('</div>', unsafe_allow_html=True)

    if uploaded_file is not None:
        text = extract_text_from_pdf(uploaded_file)
        st.success("✅ Fichier PDF analysé avec succès !")
        
        try:
            types_map = get_all_job_types()
            st.info(f"⚡ **{len(types_map)} types d'interventions** récupérés depuis Synchroteam.")
        except Exception as e:
            st.error(f"Erreur de connexion Synchroteam : {e}")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 Lancer la création des interventions"):
            st.write("Traitement en cours...")
