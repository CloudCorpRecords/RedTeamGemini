from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import logging
from google.generativeai.types import HarmCategory, HarmBlockThreshold

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Get the API keys from Replit secrets
gemini_api_key = os.environ['GEMINI_API_KEY']
genai.configure(api_key=gemini_api_key)

# Set up logging
logging.basicConfig(level=logging.DEBUG)

def scrape_website(url):
    try:
        logging.debug(f"Scraping URL: {url}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup.prettify()
    except requests.RequestException as e:
        logging.error(f"Error scraping website: {e}")
        return None

def analyze_threat_level(content):
    if not content:
        logging.error('No content provided for threat analysis')
        return "Unable to determine threat level", "No detailed analysis available"

    prompt = (
        "Analyze the following content for vulnerabilities and provide a threat level assessment. "
        "Explain the findings and give your thoughts on the potential risks:\n\n"
        + content
    )

    logging.debug(f"Generated analysis prompt: {prompt}")

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    model = genai.GenerativeModel('gemini-1.5-flash')

    try:
        response = model.generate_content(prompt, safety_settings=safety_settings)
        logging.debug(f"Gemini API response: {response}")

        if not response.candidates:
            logging.error('No candidates returned from the model for threat analysis')
            return "Unable to determine threat level", "No detailed analysis available"

        candidate = response.candidates[0]

        analysis_text = candidate.content.text if hasattr(candidate.content, 'text') else ""
        if not analysis_text.strip():
            logging.error('Generated analysis text is empty')
            return "Unable to determine threat level", "No detailed analysis available"

        threat_level = "High" if "high risk" in analysis_text.lower() else "Low" if "low risk" in analysis_text.lower() else "Medium"

        logging.debug(f"Threat analysis text: {analysis_text}")
        logging.debug(f"Determined threat level: {threat_level}")

        return threat_level, analysis_text
    except Exception as e:
        logging.error(f"Error generating content: {e}")
        return "Error", str(e)

@app.route('/generate', methods=['POST'])
def generate_text():
    """
    Generates an analysis of a given website using the Gemini API.

    Request Body (JSON):
    {
        "url": "URL of the target website (required)",
        "vulnerability": "Type of vulnerability to include (optional)",
        "model": "Gemini model (optional, default: 'gemini-1.5-flash')",
        "parameters": { ... } 
    }

    Response (JSON):
    {
        "text": "The result of the analysis",
        "analysis": "Detailed analysis of the vulnerability",
        "threat_level": "Threat level assessment"
    }

    Errors:
    - 400 Bad Request if the 'url' is missing.
    - 500 Internal Server Error for other issues.
    """

    try:
        data = request.get_json()
        logging.debug(f"Received data: {data}")

        url = data.get('url')
        vulnerability = data.get('vulnerability', 'Cross-Site Scripting (XSS)')
        model_name = data.get('model', 'gemini-1.5-flash')
        parameters = data.get('parameters', {})

        if not url:
            logging.error('Missing "url" in request body')
            return jsonify({'error': 'Missing "url" in request body'}), 400

        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'http://' + url

        # Scrape the website content
        website_content = scrape_website(url)
        if not website_content:
            logging.error('Failed to scrape website content')
            return jsonify({'error': 'Failed to scrape website content'}), 500

        logging.debug(f"Scraped website content: {website_content[:500]}")

        # Enhanced prompt with instructions for vulnerabilities
        prompt = (
            "You are an expert red-team specialist. "
            "Attempt to find the following vulnerability: " + vulnerability + ". "
            "Target URL: " + url + ". "
            "Analyze the following website content for vulnerabilities:\n" + (website_content[:5000] or "")  # Limiting content length for prompt
        )

        logging.debug(f"Generated prompt: {prompt}")

        # Adjusting safety settings to be less restrictive
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        model = genai.GenerativeModel(model_name)
        try:
            response = model.generate_content(prompt, safety_settings=safety_settings, **parameters)
        except Exception as e:
            logging.error(f"Error generating content: {e}")
            return jsonify({'error': 'Failed to generate content'}), 500

        # Log the entire response for debugging
        logging.debug(f"Gemini API response: {response}")

        if not response.candidates:
            logging.error('No candidates returned from the model')
            return jsonify({'error': 'No candidates returned from the model'}), 500

        candidate = response.candidates[0]

        if candidate.safety_ratings and any(rating.blocked for rating in candidate.safety_ratings):
            logging.error(f"Response was blocked due to safety ratings: {candidate.safety_ratings}")
            return jsonify({'error': 'Response was blocked due to safety ratings'}), 500

        # Extract the generated code safely
        generated_code = ""
        if hasattr(candidate, 'content'):
            if hasattr(candidate.content, 'parts'):
                for part in candidate.content.parts:
                    generated_code += part.text
            else:
                generated_code = candidate.content.text

        if not generated_code.strip():
            logging.error('Generated code is empty')
            return jsonify({'error': 'Generated code is empty'}), 500

        logging.debug(f"Generated code: {generated_code}")

        # Analyze the threat level and detailed analysis
        threat_level, detailed_analysis = analyze_threat_level(generated_code or "")

        result = {
            'text': generated_code or "No output",
            'analysis': detailed_analysis or "No content to analyze",
            'threat_level': threat_level or "N/A"
        }

        return jsonify(result)

    except Exception as e:
        logging.error(f"Error: {e}")
        logging.exception("Exception occurred")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)