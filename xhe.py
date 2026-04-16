from google import genai

client = genai.Client(api_key="AIzaSyCcp00__hMl_blfI5p_ziMWEhig2gBS2D0")

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Hello"
)

print(response.text)

