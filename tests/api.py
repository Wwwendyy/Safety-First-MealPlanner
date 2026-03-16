from openai import AzureOpenAI
import os
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

print("ENDPOINT:", os.environ.get("AZURE_OPENAI_ENDPOINT"))
print("DEPLOYMENT:", os.environ.get("AZURE_OPENAI_DEPLOYMENT"))
print("VERSION:", os.environ.get("AZURE_OPENAI_API_VERSION"))
print("KEY SET?:", bool(os.environ.get("AZURE_OPENAI_API_KEY")))

client = AzureOpenAI(
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)

resp = client.chat.completions.create(
    model=os.environ["AZURE_OPENAI_DEPLOYMENT"],  # 这里传 deployment 名称
    messages=[{"role":"user","content":"Say hi in one short sentence."}],
    temperature=0.0,
    max_tokens=50,
)

print(resp.choices[0].message.content)