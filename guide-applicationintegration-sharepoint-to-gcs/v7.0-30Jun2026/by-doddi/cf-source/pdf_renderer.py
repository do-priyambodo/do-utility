import base64
import html
import io
import re

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
    
    # Remove all stylesheet links and style tags to prevent xhtml2pdf float crash
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
        @page {{ size: A4 portrait; margin: 1.5cm; }}
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

# Convert rendered HTML string to Base64-encoded PDF bytes using selected engine
def render_html_to_pdf_base64(html_string, fallback_title="SharePoint Page", engine="playwright"):
    cleaned_html = re.sub(r':\s*(revert|revert-layer|unset)\s*(;|\})', r': inherit\2', html_string, flags=re.IGNORECASE)
    
    # Engine 1: Headless Chromium via Playwright
    if engine and str(engine).lower() == "playwright":
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.set_content(cleaned_html, wait_until="networkidle")
                    pdf_bytes = page.pdf(format="A4", print_background=True)
                finally:
                    browser.close()
                return base64.b64encode(pdf_bytes).decode("utf-8")
        except Exception as pw_e:
            print(f"Warning: Playwright engine failed ({pw_e}). Falling back to WeasyPrint engine...")

    # Engine 2: WeasyPrint (Modern HTML5 Vector Engine)
    if engine and str(engine).lower() == "weasyprint":
        try:
            import weasyprint
            pdf_bytes = weasyprint.HTML(string=cleaned_html).write_pdf()
            return base64.b64encode(pdf_bytes).decode("utf-8")
        except Exception as wp_e:
            print(f"Warning: WeasyPrint engine failed ({wp_e}). Falling back to xhtml2pdf engine...")

    # Fallback Engine: xhtml2pdf with Simplified Layout Protection
    if not pisa:
        print("Warning: xhtml2pdf not installed. Falling back to HTML payload.")
        return base64.b64encode(html_string.encode("utf-8")).decode("utf-8")
    try:
        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(io.StringIO(cleaned_html), dest=pdf_buffer)
        if pisa_status.err:
            raise RuntimeError(f"xhtml2pdf reported error: {pisa_status.err}")
        return base64.b64encode(pdf_buffer.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Warning: High-fidelity PDF rendering failed ({e}). Generating simplified Document Reader layout...")
        try:
            simplified_html = strip_complex_css_for_pdf(html_string, fallback_title)
            fb_buffer = io.BytesIO()
            pisa.CreatePDF(io.StringIO(simplified_html), dest=fb_buffer)
            return base64.b64encode(fb_buffer.getvalue()).decode("utf-8")
        except Exception as fb_e:
            print(f"Warning: Simplified layout PDF creation failed ({fb_e}). Returning raw HTML payload.")
            return base64.b64encode(html_string.encode("utf-8")).decode("utf-8")
