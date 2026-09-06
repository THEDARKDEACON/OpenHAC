"""Base classes for Parametric Submodules (Phase 3)."""
import logging

from openhac.core.base import Module
from openhac.database.db_manager import DatabaseManager

logger = logging.getLogger("openhac.parametric")

class SupplyChainError(Exception):
    """Raised when a parametric module cannot find a suitable component in the supply chain."""
    pass

class ParametricModule(Module):
    """A module that dynamically resolves its internal topology based on database queries.
    
    Subclasses should implement `_build_circuit(part_data: dict)` to wire up the specific IC
    found by the parametric search engine.
    """
    
    def __init__(self, name: str, category: str, **constraints):
        super().__init__(name)
        self.category = category
        self.constraints = constraints
        self._is_resolved = False
        self._db = DatabaseManager()
        
    def resolve(self) -> None:
        """Query the database and dynamically construct the sub-circuit.
        
        This should be called exactly once before the compiler generates the netlist.
        """
        if self._is_resolved:
            return
            
        logger.info(f"Resolving ParametricModule '{self.name}' (Category: {self.category})")
        
        # 1. Query the database
        search_kw = {
            k: v
            for k, v in self.constraints.items()
            if k not in ("l_value", "c_in", "c_out")
        }
        part_data, fallback = self._db.parametric_search(
            category=self.category,
            **search_kw,
        )
        
        if not part_data:
            raise SupplyChainError(
                f"No supply chain match found for {self.name} "
                f"(Category: {self.category}, Constraints: {self.constraints})"
            )
            
        logger.info(f"Parametric resolution found: {part_data.get('generic_name')} (Fallback used: {fallback})")
        
        # 2. Build the circuit topology
        self._build_circuit(part_data)
        
        self._is_resolved = True
        
    def _build_circuit(self, part_data: dict) -> None:
        """Implemented by subclasses to construct the circuit based on the chosen part."""
        raise NotImplementedError("Subclasses must implement _build_circuit.")
