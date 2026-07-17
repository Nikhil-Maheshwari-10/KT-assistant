import sys
import os
from playwright.sync_api import sync_playwright

def generate_pdf(input_html_path: str, output_pdf_path: str):
    """Render an HTML file to a PDF using headless Chromium."""
    if not os.path.exists(input_html_path):
        print(f"Error: Input file {input_html_path} does not exist.")
        sys.exit(1)

    # Read the HTML content
    with open(input_html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    with sync_playwright() as p:
        # Launch Chromium headless
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Set the HTML content
        page.set_content(html_content, wait_until="networkidle")
        
        # Wait for mermaid to render all diagrams, if any exist
        page.wait_for_function('''() => {
            const elements = document.querySelectorAll('.mermaid');
            for (let el of elements) {
                // Mermaid adds 'data-processed="true"' when it's done rendering the SVG
                if (el.getAttribute('data-processed') !== 'true') {
                    return false;
                }
            }
            return true;
        }''')
        
        # Generate the PDF
        page.pdf(
            path=output_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "1in", "bottom": "1in", "left": "1in", "right": "1in"}
        )
        
        browser.close()
    
    print(f"PDF successfully generated at {output_pdf_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_pdf.py <input.html> <output.pdf>")
        sys.exit(1)
        
    in_path = sys.argv[1]
    out_path = sys.argv[2]
    
    generate_pdf(in_path, out_path)
