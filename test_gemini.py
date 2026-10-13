import os
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

interaction = client.interactions.create(
    model="gemini-3.8-flash",
    input="Réponds simplement : Gemini fonctionne !"
)

print(interaction.output_text)
