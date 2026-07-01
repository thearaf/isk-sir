"""
İŞKUR Şırnak İlan Takip Botu
Selenium yerine requests + API/form post kullanır (Railway uyumlu)
"""

import asyncio
import json
import os
import logging
import hashlib
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.constants import ParseMode

# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
KONTROL_SURESI   = 30   # 2 dakika
KAYIT_DOSYASI    = "gorulmus_ilanlar.json"
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def gorulmus_yukle():
    if os.path.exists(KAYIT_DOSYASI):
        with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def gorulmus_kaydet(veri):
    with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)


def hash_ilan(metin):
    return hashlib.md5(metin.encode("utf-8")).hexdigest()[:12]


def aspnet_viewstate(url):
    """ASP.NET sayfasından __VIEWSTATE ve diğer hidden field'ları çeker."""
    try:
        r = SESSION.get(url, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        fields = {}
        for inp in soup.find_all("input", type="hidden"):
            name = inp.get("name", "")
            if name:
                fields[name] = inp.get("value", "")
        return fields, soup
    except Exception as e:
        log.warning(f"ViewState alınamadı ({url}): {e}")
        return {}, None


def tablo_satirlari(soup):
    """Sayfadaki tablodan satırları çeker."""
    ilanlar = []
    if not soup:
        return ilanlar
    for tablo in soup.find_all("table"):
        satirlar = tablo.find_all("tr")
        for satir in satirlar[1:]:
            hucreler = satir.find_all("td")
            if len(hucreler) >= 2:
                metin = " | ".join(h.get_text(strip=True) for h in hucreler if h.get_text(strip=True))
                if metin:
                    ilanlar.append(metin)
    return ilanlar


# ──────────────────────────────────────────────────────
# 1) TYP
# ──────────────────────────────────────────────────────
def typ_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Typ/TypArama.aspx"
    try:
        fields, soup = aspnet_viewstate(url)
        if not fields:
            return ilanlar

        # İl seçimi için dropdown name bul
        il_field = None
        for k in fields:
            if "Il" in k and "Ilce" not in k:
                il_field = k
                break

        # POST verisi
        data = dict(fields)
        if il_field:
            # ŞIRNAK il kodunu bulmaya çalış
            if soup:
                select = soup.find("select", {"id": lambda x: x and "Il" in x and "Ilce" not in x})
                if select:
                    for opt in select.find_all("option"):
                        if "IRNAK" in opt.text.upper():
                            data[il_field] = opt["value"]
                            break

        # Ara butonu
        for k in list(data.keys()):
            if "Search" in k or "Ara" in k or "Button" in k.lower():
                data[k] = "Ara"
                break

        r = SESSION.post(url, data=data, timeout=20)
        soup2 = BeautifulSoup(r.text, "html.parser")
        satirlar = tablo_satirlari(soup2)
        for s in satirlar:
            if s:
                ilanlar.append({"id": hash_ilan(s), "baslik": s, "kaynak": "TYP"})
    except Exception as e:
        log.warning(f"[TYP] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 2) IUP
# ──────────────────────────────────────────────────────
def iup_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx"
    try:
        fields, soup = aspnet_viewstate(url)
        if not fields:
            return ilanlar

        data = dict(fields)

        if soup:
            select = soup.find("select", {"id": lambda x: x and "Il" in x and "Ilce" not in x})
            if select:
                for opt in select.find_all("option"):
                    if "IRNAK" in opt.text.upper():
                        il_field = select.get("name") or select.get("id")
                        if il_field:
                            data[il_field] = opt["value"]
                        break

        r = SESSION.post(url, data=data, timeout=20)
        soup2 = BeautifulSoup(r.text, "html.parser")
        for s in tablo_satirlari(soup2):
            ilanlar.append({"id": hash_ilan(s), "baslik": s, "kaynak": "IUP"})
    except Exception as e:
        log.warning(f"[IUP] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 3) Gençlik Programı
# ──────────────────────────────────────────────────────
def genclik_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/IstIskurGenclikProgramArama.aspx"
    try:
        fields, soup = aspnet_viewstate(url)
        if not fields:
            return ilanlar

        data = dict(fields)

        if soup:
            select = soup.find("select", {"id": lambda x: x and "Il" in x and "Ilce" not in x})
            if select:
                for opt in select.find_all("option"):
                    if "IRNAK" in opt.text.upper():
                        il_field = select.get("name") or select.get("id")
                        if il_field:
                            data[il_field] = opt["value"]
                        break

        r = SESSION.post(url, data=data, timeout=20)
        soup2 = BeautifulSoup(r.text, "html.parser")
        for s in tablo_satirlari(soup2):
            ilanlar.append({"id": hash_ilan(s), "baslik": s, "kaynak": "Gençlik Programı"})
    except Exception as e:
        log.warning(f"[Gençlik] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 4) Açık İş İlanları (Kamu + Şırnak)
# ──────────────────────────────────────────────────────
def acik_is_cek():
    ilanlar = []
    url = "https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx"
    try:
        fields, soup = aspnet_viewstate(url)
        if not fields:
            return ilanlar

        data = dict(fields)

        if soup:
            # İşyeri türü: Kamu
            for sel in soup.find_all("select"):
                sel_id = sel.get("id", "") or sel.get("name", "")
                if "Tur" in sel_id or "tur" in sel_id:
                    for opt in sel.find_all("option"):
                        if "KAMU" in opt.text.upper():
                            data[sel.get("name") or sel_id] = opt["value"]
                            break

            # İl: Şırnak
            for sel in soup.find_all("select"):
                sel_id = sel.get("id", "") or sel.get("name", "")
                if "Il" in sel_id and "Ilce" not in sel_id:
                    for opt in sel.find_all("option"):
                        if "IRNAK" in opt.text.upper():
                            data[sel.get("name") or sel_id] = opt["value"]
                            break

        r = SESSION.post(url, data=data, timeout=20)
        soup2 = BeautifulSoup(r.text, "html.parser")
        for s in tablo_satirlari(soup2):
            ilanlar.append({"id": hash_ilan(s), "baslik": s, "kaynak": "Açık İş (Kamu)"})
    except Exception as e:
        log.warning(f"[Açık İş] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 5) Kurum Dışı Kamu İşçi Alım İlanları
# ──────────────────────────────────────────────────────
def kurumdisi_cek():
    ilanlar = []
    url = ("https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/"
           "?idId=sirnak&il=%C5%9E%C4%B1rnak")
    try:
        r = SESSION.get(url, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        for s in tablo_satirlari(soup):
            ilanlar.append({"id": hash_ilan(s), "baslik": s, "kaynak": "Kurum Dışı Kamu"})

        if not ilanlar:
            for css in ["article", ".list-group-item", ".ilan-item", "li"]:
                for el in soup.select(css):
                    metin = el.get_text(strip=True)
                    if metin and len(metin) > 20:
                        ilanlar.append({"id": hash_ilan(metin), "baslik": metin[:300], "kaynak": "Kurum Dışı Kamu"})
    except Exception as e:
        log.warning(f"[Kurum Dışı] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# Bildirim
# ──────────────────────────────────────────────────────
async def bildirim_gonder(bot, ilan):
    mesaj = (
        f"🔔 *YENİ İŞKUR İLANI — ŞIRNAK*\n\n"
        f"📋 *Kaynak:* {ilan['kaynak']}\n"
        f"📌 *Detay:* {ilan['baslik'][:400]}\n"
        f"🕐 *Tespit:* {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=mesaj,
        parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────
# Ana döngü
# ──────────────────────────────────────────────────────
async def kontrol_et(bot, gorulmus):
    log.info("── Kontrol başlıyor ──")
    yeni = 0

    tum_ilanlar = []
    tum_ilanlar += typ_cek()
    tum_ilanlar += iup_cek()
    tum_ilanlar += genclik_cek()
    tum_ilanlar += acik_is_cek()
    tum_ilanlar += kurumdisi_cek()

    for ilan in tum_ilanlar:
        if not ilan.get("id"):
            continue
        anahtar = f"{ilan['kaynak']}::{ilan['id']}"
        if anahtar not in gorulmus:
            gorulmus[anahtar] = True
            yeni += 1
            log.info(f"YENİ → {anahtar}")
            try:
                await bildirim_gonder(bot, ilan)
                await asyncio.sleep(1)
            except Exception as e:
                log.error(f"Bildirim hatası: {e}")

    gorulmus_kaydet(gorulmus)
    log.info(f"Tamamlandı. Yeni: {yeni} | Toplam kayıt: {len(gorulmus)}")


async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"Bot bağlandı: @{me.username}")

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            "✅ *İŞKUR Şırnak Takip Botu Yeniden Başladı*\n\n"
            "Her 2 dakikada bir kontrol ediyorum:\n"
            "• TYP (Toplum Yararına Program)\n"
            "• İUP (İşgücü Uyum Programı)\n"
            "• İŞKUR Gençlik Programı\n"
            "• Açık İş İlanları (Kamu)\n"
            "• Kurum Dışı Kamu İşçi Alım İlanları"
        ),
        parse_mode=ParseMode.MARKDOWN
    )

    gorulmus = gorulmus_yukle()

    while True:
        try:
            await kontrol_et(bot, gorulmus)
        except Exception as e:
            log.error(f"Beklenmeyen hata: {e}")
        await asyncio.sleep(KONTROL_SURESI)


if __name__ == "__main__":
    asyncio.run(main())
