import os
import logging
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

logger = logging.getLogger("QdrantMemory")

# Create local Qdrant data directory
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_PATH = "/containers/monitorbot/qdrant_data"
os.makedirs(QDRANT_PATH, exist_ok=True)

class QdrantMemory:
    def __init__(self):
        self.client = None
        self.collection_name = "resolved_incidents"
        try:
            if QDRANT_URL:
                self.client = QdrantClient(url=QDRANT_URL)
                logger.info(f"Connecting to Qdrant container at: {QDRANT_URL}")
            else:
                self.client = QdrantClient(path=QDRANT_PATH)
                logger.info(f"Using local file Qdrant storage at: {QDRANT_PATH}")
            # Check if collection exists, if not, create it
            if not self.client.collection_exists(self.collection_name):
                # Using add() automatically configures the vector size and model
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=self.client.get_fastembed_vector_params()
                )
                logger.info(f"Created Qdrant collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client: {e}")
            self.client = None

    def learn_incident(self, incident_id: str, target_id: str, root_cause: str, proposed_fix: str):
        if not self.client:
            logger.warning("Qdrant client not initialized. Skipping learning.")
            return False

        try:
            document = f"Error on {target_id}. Cause: {root_cause}. Fix: {proposed_fix}."
            payload = {
                "target_id": target_id,
                "target_type": "docker",
                "successful_command": proposed_fix
            }
            # Add to collection
            self.client.add(
                collection_name=self.collection_name,
                documents=[document],
                metadata=[payload],
                ids=[incident_id]
            )
            logger.info(f"Learned incident {incident_id} in Qdrant memory.")
            return True
        except Exception as e:
            logger.error(f"Error adding memory to Qdrant: {e}")
            return False

    def query_similar_fix(self, target_id: str, error_logs: str):
        if not self.client:
            return None

        try:
            # Check if collection exists and has points
            if not self.client.collection_exists(self.collection_name):
                return None

            # Search with filter prioritizing current target
            results = self.client.query(
                collection_name=self.collection_name,
                query_text=error_logs,
                query_filter=Filter(
                    should=[
                        FieldCondition(
                            key="target_id",
                            match=MatchValue(value=target_id)
                        )
                    ]
                ),
                limit=1
            )

            if results:
                match = results[0]
                # Check similarity score (e.g. score > 0.7)
                # Note: fastembed model distance is typically cosine similarity
                logger.info(f"Qdrant query found match. Score: {match.score}")
                if match.score > 0.65:
                    return match
            return None
        except Exception as e:
            logger.error(f"Error querying Qdrant: {e}")
            return None

    def semantic_search(self, query_text: str, limit: int = 5):
        if not self.client:
            return []
        try:
            if not self.client.collection_exists(self.collection_name):
                return []
            results = self.client.query(
                collection_name=self.collection_name,
                query_text=query_text,
                limit=limit
            )
            return results
        except Exception as e:
            logger.error(f"Error doing semantic search in Qdrant: {e}")
            return []

qdrant_mem = QdrantMemory()
