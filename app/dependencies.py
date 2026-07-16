"""
app/dependencies.py
~~~~~~~~~~~~~~~~~~~
Parses docker-compose files to build a dependency tree and checks if any
parent dependencies have active, unresolved incidents.
"""
import os
import yaml
import logging

logger = logging.getLogger("DependencyTracker")

_dependency_cache = None

def load_compose_dependencies(root_dir: str = "/containers") -> dict:
    """
    Scans all docker-compose.yaml / docker-compose.yml files and builds a mapping of:
    container_name -> list of container_names it depends on
    """
    global _dependency_cache
    if _dependency_cache is not None:
        return _dependency_cache

    deps = {}
    service_to_container = {} # Maps (compose_path, service_key) -> container_name

    # First pass: collect all service-to-container mappings
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file in ["docker-compose.yaml", "docker-compose.yml"]:
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r") as f:
                        data = yaml.safe_load(f)
                        if not data or "services" not in data:
                            continue
                        
                        services = data["services"]
                        for service_key, config in services.items():
                            if not config:
                                continue
                            c_name = config.get("container_name") or service_key
                            service_to_container[(filepath, service_key)] = c_name
                except Exception as e:
                    logger.debug(f"Failed to parse compose file for service map {filepath}: {e}")

    # Second pass: build dependencies using container names
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file in ["docker-compose.yaml", "docker-compose.yml"]:
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r") as f:
                        data = yaml.safe_load(f)
                        if not data or "services" not in data:
                            continue
                        
                        services = data["services"]
                        for service_key, config in services.items():
                            if not config:
                                continue
                            c_name = config.get("container_name") or service_key
                            
                            # Resolve depends_on
                            depends_on = config.get("depends_on")
                            resolved_deps = []
                            if depends_on:
                                # depends_on can be a list or a dict
                                dep_keys = []
                                if isinstance(depends_on, list):
                                    dep_keys = depends_on
                                elif isinstance(depends_on, dict):
                                    dep_keys = list(depends_on.keys())
                                
                                for dk in dep_keys:
                                    dep_cname = service_to_container.get((filepath, dk)) or dk
                                    resolved_deps.append(dep_cname)
                            
                            if resolved_deps:
                                deps[c_name] = resolved_deps
                except Exception as e:
                    logger.debug(f"Failed to parse dependencies in compose file {filepath}: {e}")

    _dependency_cache = deps
    logger.info(f"Loaded dependencies for {len(deps)} containers.")
    return deps

def check_parent_incidents(target_id: str, db) -> list:
    """
    Checks if the target container has any parent dependencies with active, unresolved incidents.
    Returns a list of active incident objects for parent dependencies.
    """
    from app.database import Incident
    
    deps_map = load_compose_dependencies()
    parents = deps_map.get(target_id, [])
    if not parents:
        return []

    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    active_parents = []
    
    for parent in parents:
        # Check if the parent has an active incident
        incident = db.query(Incident).filter(
            Incident.target_id == parent,
            Incident.status.in_(active_statuses)
        ).first()
        if incident:
            active_parents.append(incident)
            
    return active_parents
