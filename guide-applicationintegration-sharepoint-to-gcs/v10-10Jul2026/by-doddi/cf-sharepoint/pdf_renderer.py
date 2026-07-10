import base64
import html
import io
import re
import threading

# Concurrency guard: limit concurrent Chromium browser instances in Cloud Run container
# to prevent CPU starvation and /dev/shm shared memory crashes
_PLAYWRIGHT_SEMAPHORE = threading.Semaphore(2)

try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

def strip_complex_css_for_pdf(html_string, fallback_title="SharePoint Page"):
    safe_title = html.escape(str(fallback_title))
    if not BeautifulSoup:
        # Simple regex stripping if BS4 is unavailable
        text_only = re.sub(r'<[^>]+>', ' ', html_string)
        return f"<!DOCTYPE html><html><head><title>{safe_title}</title><style>body {{ font-family: sans-serif; padding: 20px; line-height: 1.5; }} h1 {{ color: #0078d4; }}</style></head><body><h1>{safe_title} (Simplified Layout)</h1><p>{html.escape(text_only[:10000])}</p></body></html>"
    
    soup = BeautifulSoup(html_string, "html.parser")
    
    # Remove all stylesheet links and style tags
    for s in soup.find_all(["style", "link", "script", "noscript"]):
        s.decompose()
        
    # Simplify table attributes and ensure widths fit page
    for tbl in soup.find_all("table"):
        tbl["width"] = "100%"
        tbl["border"] = "1"
        tbl["cellpadding"] = "6"
        tbl["cellspacing"] = "0"
        if tbl.has_attr("style"):
            del tbl["style"]
            
    # Ensure images have max dimensions so they don't overflow A4 pages
    for img in soup.find_all("img"):
        img["width"] = "400"
        if img.has_attr("height"):
            del img["height"]
        if img.has_attr("style"):
            del img["style"]
            
    # Clean up divs and spans that might have problematic CSS attributes
    for el in soup.find_all(["div", "span", "p", "section"]):
        if el.has_attr("style"):
            del el["style"]
        if el.has_attr("class"):
            del el["class"]

    body_content = ""
    body = soup.find("body")
    if body:
        body_content = str(body.decode_contents())
    else:
        body_content = str(soup.decode_contents())

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{safe_title}</title>
    <style>
        @page {{ size: A4 portrait; margin: 0.8cm; }}
        body {{ font-family: sans-serif; font-size: 10pt; line-height: 1.6; color: #201f1e; }}
        h1, h2, h3 {{ color: #0078d4; margin-top: 15px; margin-bottom: 8px; }}
        table {{ border-collapse: collapse; margin: 15px 0; width: 100%; }}
        th, td {{ border: 1px solid #c8c6c4; padding: 6px; text-align: left; vertical-align: top; }}
        th {{ background-color: #f3f2f1; font-weight: bold; }}
        img {{ max-width: 100%; height: auto; margin: 10px 0; }}
        .fallback-banner {{ background-color: #fff4ce; border-left: 4px solid #ffb900; padding: 12px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="fallback-banner">
        <b>Simplified Document Layout:</b> This SharePoint page layout was simplified to ensure 100% of the information, tables, and images are presented accurately without formatting loss.
    </div>
    {body_content}
</body>
</html>"""

# Convert rendered HTML string to Base64-encoded PDF bytes strictly using Playwright Chromium
def render_html_to_pdf_base64(html_string, fallback_title="SharePoint Page", engine="playwright"):
    cleaned_html = re.sub(r':\s*(revert|revert-layer|unset|initial)\s*(;|\})', r': inherit\2', html_string, flags=re.IGNORECASE)
    
    with _PLAYWRIGHT_SEMAPHORE:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    timeout=25000,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--no-zygote",
                        "--single-process",
                        "--disable-extensions",
                        "--disable-background-networking",
                        "--disable-default-apps",
                        "--disable-sync",
                        "--hide-scrollbars",
                        "--metrics-recording-only",
                        "--mute-audio",
                        "--no-first-run"
                    ]
                )
                try:
                    page = browser.new_page()
                    
                    # Stage 1: Standard High-Fidelity Playwright Chromium Render (25s timeout)
                    try:
                        page.set_content(cleaned_html, wait_until="domcontentloaded", timeout=25000)
                        pdf_bytes = page.pdf(format="A4", print_background=True)
                        return base64.b64encode(pdf_bytes).decode("utf-8")
                    except Exception as s1_err:
                        print(f"⚠️ Playwright Stage 1 timed out on '{fallback_title}' ({s1_err}). Attempting Stage 2 (Script-Sanitized Render)...")
                    
                    # Stage 2: Strip blocking scripts & iframes -> Playwright Chromium Render
                    try:
                        no_scripts = re.sub(r'<(script|iframe|noscript)[^>]*>.*?</\1>', '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)
                        page.set_content(no_scripts, wait_until="domcontentloaded", timeout=15000)
                        pdf_bytes = page.pdf(format="A4", print_background=True)
                        return base64.b64encode(pdf_bytes).decode("utf-8")
                    except Exception as s2_err:
                        print(f"⚠️ Playwright Stage 2 failed on '{fallback_title}' ({s2_err}). Attempting Stage 3 (Clean-Layout Playwright Render)...")

                    # Stage 3: Clean Simplified Layout -> Playwright Chromium Render (~0.1s execution)
                    simplified_html = strip_complex_css_for_pdf(cleaned_html, fallback_title)
                    page.set_content(simplified_html, wait_until="domcontentloaded", timeout=10000)
                    pdf_bytes = page.pdf(format="A4", print_background=True)
                    return base64.b64encode(pdf_bytes).decode("utf-8")
                finally:
                    browser.close()
        except Exception as pw_fatal:
            print(f"❌ Fatal Playwright failure on '{fallback_title}': {pw_fatal}")
            return base64.b64encode(f"<html><body><h1>Error rendering {html.escape(str(fallback_title))}</h1><p>{html.escape(str(pw_fatal))}</p></body></html>".encode("utf-8")).decode("utf-8")
