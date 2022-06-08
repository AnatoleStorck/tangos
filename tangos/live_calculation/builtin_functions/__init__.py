import numpy as np
from sqlalchemy import alias

import tangos
from tangos.util import consistent_collection

from ... import core
from ... import temporary_halolist as thl
from ...core import extraction_patterns
from .. import (BuiltinFunction, FixedInput, FixedNumericInput, LiveProperty,
                StoredProperty)


@BuiltinFunction.register
def match(source_halos, target):
    timestep = consistent_collection.ConsistentCollection(source_halos).timestep
    if target is None:
        results = [None]*len(source_halos)
    else:
        from ... import relation_finding
        if not isinstance(target, core.Base):
            target = tangos.get_item(target, core.Session.object_session(timestep))
        results = relation_finding.MultiSourceMultiHopStrategy(source_halos, target).all()
    # if following assert fails, it might be duplicate links in the database which the
    # current MultiSourceMultiHop implementation cannot de-duplicate:
    assert len(results) == len(source_halos)
    return np.array(results, dtype=object)
match.set_input_options(0, provide_proxy=True, assert_class = FixedInput)

@BuiltinFunction.register
def later(source_halos, num_steps):
    timestep = consistent_collection.ConsistentCollection(source_halos).timestep.get_next(num_steps)
    return match(source_halos, timestep)

later.set_input_options(0, provide_proxy=True, assert_class = FixedNumericInput)


@BuiltinFunction.register
def earlier(source_halos, num_steps):
    return later(source_halos, -num_steps)

earlier.set_input_options(0, provide_proxy=True, assert_class = FixedNumericInput)

@BuiltinFunction.register
def at_this_timestep(source_halos, halo_id):
    session = core.Session.object_session(source_halos[0])
    typecode, SimulationObjectBase.typecode_and_number_from_human_identifier(halo_identifier)
    with thl.temporary_halolist_table(session,
                                      [h.id for h in source_halos],
                                      halo_id) as table:



        original_halo = alias(core.halo.SimulationObjectBase)
        target_halo = alias(core.halo.SimulationObjectBase)

        session.query(table.c.id, core.halo.SimulationObjectBase).\
            select_from(table).\
            outerjoin(core.halo.SimulationObjectBase, table.c.halo_id == core.halo.SimulationObjectBase.id).order_by(table.c.id)



@BuiltinFunction.register
def latest(source_halos):
    from .search import find_descendant
    return find_descendant(source_halos, LiveProperty('t').proxy_value(), 'max')


@BuiltinFunction.register
def earliest(source_halos):
    from .search import find_progenitor
    return find_progenitor(source_halos, LiveProperty('t').proxy_value(), 'min')

@BuiltinFunction.register
def has_property(source_halos, property):
    from ...util import is_not_none
    return is_not_none(property)

has_property.set_input_options(0, provide_proxy=False, assert_class=StoredProperty)

@has_property.set_initialisation
def has_property_init(input):
    input.set_extraction_pattern(extraction_patterns.HaloPropertyRawValueGetter())


from . import arithmetic, array, link, reassembly, search
