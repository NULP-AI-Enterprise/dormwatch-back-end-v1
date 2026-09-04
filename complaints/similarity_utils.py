from sentence_transformers import SentenceTransformer

# Load the model lazily.
# all-MiniLM-L6-v2 is fast and uses 384 dimensions.
MODEL_NAME = 'all-MiniLM-L6-v2'
model = None

def get_model():
    global model
    if model is None:
        model = SentenceTransformer(MODEL_NAME)
    return model

def generate_embedding(text):
    if not text:
        return None
    m = get_model()
    # encode returns a numpy array, we need a list of floats for pgvector
    embedding = m.encode(text)
    return embedding.tolist()
