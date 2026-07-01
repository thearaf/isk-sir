"""
İŞKUR Şırnak İlan Takip Botu
Selenium + Dockerfile ile Railway'de çalışır
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
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
KONTROL_SURESI   = 30   # 30 saniye
KAYIT_DOSYASI    = "gorulmus_ilanlar.json"
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)


def tarayici_ac():
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/chromium")

    driver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=opts)
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


def il_sec(driver, wait, il_text="ŞIRNAK"):
    """İl dropdown'ından Şırnak seç."""
    for xpath in [
        "//select[contains(@id,'Il') and not(contains(@id,'Ilce'))]",
        "//select[contains(@id,'il') and not(contains(@id,'ilce'))]",
        "//select[contains(@name,'Il') and not(contains(@name,'Ilce'))]",
    ]:
        try:
            el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            Select(el).select_by_visible_text(il_text)
            return True
        except Exception:
            continue
    return False


def ara_butonuna_bas(driver):
    for xpath in [
        "//input[@value='Ara']",
        "//a[contains(@id,'Search')]",
        "//input[contains(@id,'Search')]",
        "//input[contains(@id,'Ara')]",
    ]:
        try:
            driver.find_element(By.XPATH, xpath).click()
            return True
        except Exception:
            continue
    return False


def sonuc_tablosunu_oku(driver, kaynak, min_sutun=2):
    """Sadece sonuç grid tablosunu okur, form/navigasyon tablolarını atlar."""
    ilanlar = []
    try:
        # GridView veya sonuç tablosu — id'si genellikle GridView içerir
        tablolar = driver.find_elements(By.XPATH,
            "//table[contains(@id,'Grid') or contains(@id,'grid') or contains(@class,'grid')]")

        if not tablolar:
            # GridView yoksa en büyük tabloyu al
            tablolar = driver.find_elements(By.TAG_NAME, "table")
            tablolar = sorted(tablolar, key=lambda t: len(t.find_elements(By.TAG_NAME, "tr")), reverse=True)

        for tablo in tablolar[:1]:
            satirlar = tablo.find_elements(By.TAG_NAME, "tr")
            if len(satirlar) < 2:
                continue
            for satir in satirlar[1:]:
                hucreler = satir.find_elements(By.TAG_NAME, "td")
                if len(hucreler) < min_sutun:
                    continue
                metin = " | ".join(h.text.strip() for h in hucreler if h.text.strip())
                if metin and len(metin) > 3 and metin not in ("Ara | Temizle",):
                    ilan_no = hucreler[0].text.strip()
                    ilanlar.append({
                        "id": ilan_no or metin[:40],
                        "baslik": metin,
                        "kaynak": kaynak
                    })
    except Exception as e:
        log.warning(f"[{kaynak}] Tablo okuma hatası: {e}")
    return ilanlar


# ──────────────────────────────────────────────────────
# 1) TYP
# ──────────────────────────────────────────────────────
def typ_cek(driver):
    try:
        driver.get("https://esube.iskur.gov.tr/Typ/TypArama.aspx")
        wait = WebDriverWait(driver, 20)
        il_sec(driver, wait)
        ara_butonuna_bas(driver)
        wait.until(EC.presence_of_element_located((By.XPATH, "//table[contains(@id,'Grid')]")))
        return sonuc_tablosunu_oku(driver, "TYP")
    except Exception as e:
        log.warning(f"[TYP] Hata: {e}")
        return []


# ──────────────────────────────────────────────────────
# 2) IUP
# ──────────────────────────────────────────────────────
def iup_cek(driver):
    try:
        driver.get("https://esube.iskur.gov.tr/Istihdam/IstIupArama.aspx")
        wait = WebDriverWait(driver, 20)
        il_sec(driver, wait)
        ara_butonuna_bas(driver)
        wait.until(EC.presence_of_element_located((By.XPATH, "//table[contains(@id,'Grid')]")))
        return sonuc_tablosunu_oku(driver, "IUP")
    except Exception as e:
        log.warning(f"[IUP] Hata: {e}")
        return []


# ──────────────────────────────────────────────────────
# 3) Gençlik Programı
# ──────────────────────────────────────────────────────
def genclik_cek(driver):
    try:
        driver.get("https://esube.iskur.gov.tr/Istihdam/IstIskurGenclikProgramArama.aspx")
        wait = WebDriverWait(driver, 20)
        il_sec(driver, wait)
        ara_butonuna_bas(driver)
        wait.until(EC.presence_of_element_located((By.XPATH, "//table[contains(@id,'Grid')]")))
        return sonuc_tablosunu_oku(driver, "Gençlik Programı")
    except Exception as e:
        log.warning(f"[Gençlik] Hata: {e}")
        return []


# ──────────────────────────────────────────────────────
# 4) Açık İş (Kamu + Şırnak)
# ──────────────────────────────────────────────────────
def acik_is_cek(driver):
    try:
        driver.get("https://esube.iskur.gov.tr/Istihdam/AcikIsIlanAra.aspx")
        wait = WebDriverWait(driver, 20)

        # İşyeri Türü: Kamu
        for xpath in [
            "//select[contains(@id,'IsyeriTuru')]",
            "//select[contains(@id,'isyeriTuru')]",
            "//select[contains(@id,'Tur') and not(contains(@id,'Il'))]",
        ]:
            try:
                el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                Select(el).select_by_visible_text("KAMU")
                break
            except Exception:
                continue

        il_sec(driver, wait)
        ara_butonuna_bas(driver)
        wait.until(EC.presence_of_element_located((By.XPATH, "//table[contains(@id,'Grid')]")))
        return sonuc_tablosunu_oku(driver, "Açık İş (Kamu)")
    except Exception as e:
        log.warning(f"[Açık İş] Hata: {e}")
        return []


# ──────────────────────────────────────────────────────
# 5) Kurum Dışı Kamu İşçi Alım
# ──────────────────────────────────────────────────────
def kurumdisi_cek(driver):
    ilanlar = []
    try:
        driver.get(
            "https://www.iskur.gov.tr/ilanlar/kurumdisi-kamu-isci-alim-ilanlari/"
            "?idId=sirnak&il=%C5%9E%C4%B1rnak"
        )
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))

        # İlan listesi — genellikle article veya li içinde
        for css in [
            "article.ilan", ".ilan-listesi li", ".liste-ilan li",
            "table.ilanlar tr", ".search-result-item", ".job-item"
        ]:
            ogeler = driver.find_elements(By.CSS_SELECTOR, css)
            for oge in ogeler:
                metin = oge.text.strip()
                if metin and len(metin) > 15:
                    ilanlar.append({
                        "id": metin[:50],
                        "baslik": metin[:400],
                        "kaynak": "Kurum Dışı Kamu"
                    })
            if ilanlar:
                break

        # Hiç bulunamazsa tablo dene
        if not ilanlar:
            for tablo in driver.find_elements(By.TAG_NAME, "table"):
                satirlar = tablo.find_elements(By.TAG_NAME, "tr")
                if len(satirlar) < 2:
                    continue
                baslik_row = satirlar[0].text.strip().upper()
                if any(k in baslik_row for k in ["İLAN", "KURUM", "TARİH", "BAŞVURU"]):
                    for satir in satirlar[1:]:
                        hucreler = satir.find_elements(By.TAG_NAME, "td")
                        if len(hucreler) >= 2:
                            metin = " | ".join(h.text.strip() for h in hucreler if h.text.strip())
                            if metin:
                                ilanlar.append({
                                    "id": hucreler[0].text.strip() or metin[:40],
                                    "baslik": metin,
                                    "kaynak": "Kurum Dışı Kamu"
                                })
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
            "✅ *İŞKUR Şırnak Takip Botu Başladı*\n\n"
            "Her 30 saniyede bir kontrol ediyorum:\n"
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
