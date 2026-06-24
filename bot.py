"""
İŞKUR Şırnak İlan Takip Botu
- Her 2 dakikada bir 5 sayfayı kontrol eder
- Yeni ilan gelince Telegram bildirimi atar
"""

import asyncio
import json
import os
import logging
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# ─────────────────────────────────────────────
# AYARLAR
# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = "8650054825:AAE9_yjdgQ6jujUUSFkD71_ptZaEONbON1I"
TELEGRAM_CHAT_ID = "495947944"
KONTROL_SURESI   = 120   # 2 dakika
KAYIT_DOSYASI    = "gorulmus_ilanlar.json"
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)


def tarayici_ac():
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(30)
    return driver


def gorulmus_yukle():
    if os.path.exists(KAYIT_DOSYASI):
        with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def gorulmus_kaydet(veri):
    with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)


def tablo_satirlarini_cek(driver, tablo_css, kaynak):
    """Genel tablo satırı okuyucu."""
    ilanlar = []
    try:
        satirlar = driver.find_elements(By.CSS_SELECTOR, tablo_css + " tr")
        for satir in satirlar[1:]:
            hucreler = satir.find_elements(By.TAG_NAME, "td")
            if len(hucreler) >= 2:
                id_  = hucreler[0].text.strip()
                ozet = " | ".join(h.text.strip() for h in hucreler if h.text.strip())
                if id_:
                    ilanlar.append({"id": id_, "baslik": ozet, "kaynak": kaynak})
    except Exception as e:
        log.warning(f"[{kaynak}] Tablo okuma hatası: {e}")
    return ilanlar


def il_sec_ve_ara(driver, wait, il_text="ŞIRNAK"):
    """İl seçimi ve Ara butonu — birden fazla olası selector dener."""
    # İl dropdown
    for xpath in [
        "//select[contains(@id,'Il') and not(contains(@id,'Ilce'))]",
        "//select[contains(@id,'il') and not(contains(@id,'ilce'))]",
        "//select[contains(@name,'Il')]",
    ]:
        try:
            el = driver.find_element(By.XPATH, xpath)
            Select(el).select_by_visible_text(il_text)
            break
        except Exception:
            continue

    # Ara butonu
    for xpath in [
        "//input[@value='Ara']",
        "//input[contains(@id,'Search')]",
        "//input[contains(@id,'Ara')]",
        "//a[contains(@id,'Search')]",
    ]:
        try:
            driver.find_element(By.XPATH, xpath).click()
            break
        except Exception:
            continue

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
    except Exception:
        pass


# ──────────────────────────────────────────────────────
# 1) TYP — Toplum Yararına Program
# ──────────────────────────────────────────────────────
def typ_cek(driver):
    ilanlar = []
    try:
        driver.get("https://esube.iskur.gov.tr/Typ/TypArama.aspx")
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "select")))

        # TYP'de il alanı farklı id ile geliyor
        for xpath in [
            "//select[contains(@id,'ddlIl')]",
            "//select[contains(@id,'Il')]",
        ]:
            try:
                Select(driver.find_element(By.XPATH, xpath)).select_by_visible_text("ŞIRNAK")
                break
            except Exception:
                continue

        for xpath in ["//input[@value='Ara']", "//input[contains(@id,'Search')]"]:
            try:
                driver.find_element(By.XPATH, xpath).click()
                break
            except Exception:
                continue

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
        except Exception:
            pass

        ilanlar = tablo_satirlarini_cek(driver, "table", "TYP")
    except Exception as e:
        log.warning(f"[TYP] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 2) İUP — İşgücü Uyum Programı
# ──────────────────────────────────────────────────────
def iup_cek(driver):
    ilanlar = []
    try:
        driver.get("https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx")
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "select")))
        il_sec_ve_ara(driver, wait)
        ilanlar = tablo_satirlarini_cek(driver, "table", "IUP")
    except Exception as e:
        log.warning(f"[IUP] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 3) İŞKUR Gençlik Programı
# ──────────────────────────────────────────────────────
def genclik_cek(driver):
    ilanlar = []
    try:
        driver.get("https://esube.iskur.gov.tr/Istihdam/IstIskurGenclikProgramArama.aspx")
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "select")))

        # "ŞIRNAK" veya "ŞIRNAK ÜNİVERSİTESİ" — ikisini de dene
        for il_text in ["ŞIRNAK", "ŞIRNAK ÜNİVERSİTESİ"]:
            for xpath in [
                "//select[contains(@id,'Il') and not(contains(@id,'Ilce'))]",
                "//select[contains(@id,'il') and not(contains(@id,'ilce'))]",
            ]:
                try:
                    Select(driver.find_element(By.XPATH, xpath)).select_by_visible_text(il_text)
                    break
                except Exception:
                    continue

            for xpath in ["//input[@value='Ara']", "//input[contains(@id,'Search')]"]:
                try:
                    driver.find_element(By.XPATH, xpath).click()
                    break
                except Exception:
                    continue

            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
            except Exception:
                pass

            ilanlar += tablo_satirlarini_cek(driver, "table", f"Gençlik Programı ({il_text})")

    except Exception as e:
        log.warning(f"[Gençlik] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 4) Açık İş İlanları (Kamu + Şırnak)
# ──────────────────────────────────────────────────────
def acik_is_cek(driver):
    ilanlar = []
    try:
        driver.get("https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx")
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "select")))

        # İşyeri Türü: Kamu
        for xpath in [
            "//select[contains(@id,'IsyeriTuru')]",
            "//select[contains(@id,'isyeriTuru')]",
            "//select[contains(@id,'Tur')]",
        ]:
            try:
                Select(driver.find_element(By.XPATH, xpath)).select_by_visible_text("KAMU")
                break
            except Exception:
                continue

        il_sec_ve_ara(driver, wait)
        ilanlar = tablo_satirlarini_cek(driver, "table", "Açık İş (Kamu-Şırnak)")
    except Exception as e:
        log.warning(f"[Açık İş] Hata: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 5) Kurum Dışı Kamu İşçi Alım İlanları
# ──────────────────────────────────────────────────────
def kurumdisi_cek(driver):
    ilanlar = []
    try:
        driver.get(
            "https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/"
            "?idId=sirnak&il=%C5%9E%C4%B1rnak"
        )
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table, article, .list-group, .ilan")))

        # Tablo tabanlı
        satirlar = driver.find_elements(By.CSS_SELECTOR, "table tr")
        for satir in satirlar[1:]:
            hucreler = satir.find_elements(By.TAG_NAME, "td")
            if len(hucreler) >= 2:
                id_  = hucreler[0].text.strip()
                ozet = " | ".join(h.text.strip() for h in hucreler if h.text.strip())
                if id_:
                    ilanlar.append({"id": id_, "baslik": ozet, "kaynak": "Kurum Dışı Kamu"})

        # Tablo yoksa liste/article
        if not ilanlar:
            for css in ["article", ".list-group-item", "li.ilan", ".ilan-item"]:
                ogeler = driver.find_elements(By.CSS_SELECTOR, css)
                for oge in ogeler:
                    metin = oge.text.strip()
                    if metin:
                        ilanlar.append({
                            "id": metin[:80],
                            "baslik": metin,
                            "kaynak": "Kurum Dışı Kamu"
                        })
                if ilanlar:
                    break

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
        f"🆔 *İlan No:* `{ilan['id']}`\n"
        f"📌 *Detay:* {ilan['baslik'][:300]}\n"
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

    driver = tarayici_ac()
    try:
        tum_ilanlar = []
        tum_ilanlar += typ_cek(driver)
        tum_ilanlar += iup_cek(driver)
        tum_ilanlar += genclik_cek(driver)
        tum_ilanlar += acik_is_cek(driver)
        tum_ilanlar += kurumdisi_cek(driver)
    finally:
        driver.quit()

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
                await asyncio.sleep(1)  # rate-limit koruması
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
            "✅ *İŞKUR Şırnak Takip Botu Başladı*\n\n"
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
