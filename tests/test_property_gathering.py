import halo_db as db
import numpy as np
import numpy.testing as npt
import properties
from halo_db import testing
from halo_db.testing import add_symmetric_link
import os

def setup():
    # This DB cannot be in RAM -- otherwise connections tests do not work (as only one connection is ever
    # created to a RAM database)
    db.init_db("sqlite:///temporary_testing.db")

    session = db.core.internal_session

    sim = db.Simulation("sim")

    session.add(sim)

    ts1 = db.TimeStep(sim,"ts1",False)
    ts2 = db.TimeStep(sim,"ts2",False)
    ts3 = db.TimeStep(sim,"ts3",False)

    session.add_all([ts1,ts2,ts3])

    ts1.time_gyr = 1
    ts2.time_gyr = 2
    ts3.time_gyr = 3

    ts1.redshift = 10
    ts2.redshift = 5
    ts3.redshift = 0

    ts1_h1 = db.Halo(ts1,1,1000,0,0,0)
    ts1_h2 = db.Halo(ts1,2,900,0,0,0)
    ts1_h3 = db.Halo(ts1,3,800,0,0,0)
    ts1_h4 = db.Halo(ts1,4,300,0,0,0)

    session.add_all([ts1_h1,ts1_h2,ts1_h3,ts1_h4])

    ts2_h1 = db.Halo(ts2,1,1000,0,0,0)
    ts2_h2 = db.Halo(ts2,2,900,0,0,0)
    ts2_h3 = db.Halo(ts2,3,800,0,0,0)
    ts2_h4 = db.Halo(ts2,4,300,0,0,0)



    session.add_all([ts2_h1,ts2_h2,ts2_h3,ts2_h4])



    ts3_h1 = db.Halo(ts3,1,2000,0,0,0)
    ts3_h2 = db.Halo(ts3,2,800,0,0,0)
    ts3_h3 = db.Halo(ts3,3,300,0,0,0)

    session.add_all([ts3_h1,ts3_h2,ts3_h3])


    add_symmetric_link(ts1_h1, ts2_h1)
    add_symmetric_link(ts1_h2, ts2_h2)
    add_symmetric_link(ts1_h3, ts2_h3)
    add_symmetric_link(ts1_h4, ts2_h4)

    add_symmetric_link(ts2_h1, ts3_h1)
    add_symmetric_link(ts2_h2, ts3_h2)
    add_symmetric_link(ts2_h3, ts3_h3)

    for i,h in enumerate([ts1_h1,ts1_h2,ts1_h3,ts1_h4,ts2_h1,ts2_h2,ts2_h3,ts2_h4,ts3_h1,ts3_h2,ts3_h3]):
        h['Mvir'] = float(i+1)
        h['Rvir'] = float(i+1)*0.1

    for ts in ts1, ts2, ts3:
        ts1_h1_bh = db.core.BH(ts,1)
        ts1_h2_bh = db.core.BH(ts,2)
        ts1_h3_bh = db.core.BH(ts,3)
        ts1_h3_bh2 = db.core.BH(ts,4)


        session.add_all([ts1_h1_bh, ts1_h2_bh, ts1_h3_bh, ts1_h3_bh2])

        for i,h in enumerate([ts1_h1_bh, ts1_h2_bh, ts1_h3_bh, ts1_h3_bh2]):
            h['hole_mass'] = float(i+1)*100
            h['hole_spin'] = 1000-float(i+1)*100


        ts.halos.filter_by(halo_number=1).first()["BH"] = ts1_h1_bh
        ts.halos.filter_by(halo_number=2).first()["BH"] = ts1_h2_bh
        ts.halos.filter_by(halo_number=3).first()["BH"] = ts1_h3_bh, ts1_h3_bh2

    for ts_a, ts_b in (ts1, ts2), (ts2, ts3):
        assert isinstance(ts_a, db.TimeStep)
        assert isinstance(ts_b, db.TimeStep)
        add_symmetric_link(ts_a.halos.filter_by(halo_type=1).first(), ts_b.halos.filter_by(halo_type=1).first())


    db.core.internal_session.commit()

def teardown():
    os.remove("temporary_testing.db")

class TestProperty(properties.LiveHaloProperties):
    @classmethod
    def name(self):
        return "RvirPlusMvir"

    def requires_property(self):
        return "Mvir", "Rvir"

    def live_calculate(self, halo):
        return halo["Mvir"]+halo["Rvir"]

class TestErrorProperty(properties.LiveHaloProperties):

    @classmethod
    def name(self):
        return "RvirPlusMvirMiscoded"

    @classmethod
    def requires_simdata(self):
        return False

    def requires_property(self):
        return "Mvir",

    def live_calculate(self, halo):
        return halo["Mvir"]+halo["Rvir"]

class TestPropertyWithParameter(properties.LiveHaloProperties):
    @classmethod
    def name(cls):
        return "squared"

    def live_calculate(self, halo, value):
        return value**2

class TestPathChoice(properties.LiveHaloProperties):
    num_calls = 0

    def __init__(self, simulation, criterion="hole_mass"):
        super(TestPathChoice, self).__init__(simulation, criterion)
        assert isinstance(criterion, basestring), "Criterion must be a named BH property"
        self.criterion = criterion

    @classmethod
    def name(cls):
        return "my_BH"

    def requires_property(self):
        return "BH", "BH."+self.criterion

    def live_calculate(self, halo, criterion="hole_mass"):
        type(self).num_calls+=1
        bh_links = halo["BH"]
        if isinstance(bh_links,list):
            for lk in bh_links:
                print lk.keys()
            vals = [lk[criterion] if criterion in lk else self.default_val for lk in bh_links]
            return bh_links[np.argmax(vals)]
        else:
            return bh_links


def test_gather_property():
    Mv,  = db.get_timestep("sim/ts2").gather_property("Mvir")
    npt.assert_allclose(Mv,[5,6,7,8])

    Mv, Rv  = db.get_timestep("sim/ts1").gather_property("Mvir", "Rvir")
    npt.assert_allclose(Mv,[1,2,3,4])
    npt.assert_allclose(Rv,[0.1,0.2,0.3,0.4])

def test_gather_function():

    Vv, = db.get_timestep("sim/ts1").gather_property("RvirPlusMvir()")
    npt.assert_allclose(Vv,[1.1,2.2,3.3,4.4])

    Vv, = db.get_timestep("sim/ts2").gather_property("RvirPlusMvir()")
    npt.assert_allclose(Vv,[5.5,6.6,7.7,8.8])


def test_gather_function_fails():
    with npt.assert_raises(KeyError):
        # The following should fail.
        # If it does not raise a keyerror, the live calculation has ignored the directive
        # to only load in the named properties.
        Vv, = db.get_timestep("sim/ts1").gather_property("RvirPlusMvirMiscoded()")

def test_gather_function_with_parameter():
    res, = db.get_timestep("sim/ts1").gather_property("squared(Mvir)")
    npt.assert_allclose(res, [1.0, 4.0, 9.0, 16.0])


def test_gather_linked_property():
    BH_mass, = db.get_timestep("sim/ts1").gather_property("BH.hole_mass")
    npt.assert_allclose(BH_mass, [100.,200.,300.])

    BH_mass, Mv = db.get_timestep("sim/ts1").gather_property("BH.hole_mass","Mvir")
    npt.assert_allclose(BH_mass, [100.,200.,300.])
    npt.assert_allclose(Mv, [1.,2.,3.])

def test_gather_linked_property_with_fn():
    BH_mass, Mv = db.get_timestep("sim/ts1").gather_property('my_BH().hole_mass',"Mvir")
    npt.assert_allclose(BH_mass, [100.,200.,400.])
    npt.assert_allclose(Mv, [1.,2.,3.]) 

    BH_mass, Mv = db.get_timestep("sim/ts1").gather_property('my_BH("hole_spin").hole_mass',"Mvir")
    npt.assert_allclose(BH_mass, [100.,200.,300.])
    npt.assert_allclose(Mv, [1.,2.,3.])

def test_path_factorisation():

    TestPathChoice.num_calls = 0

    #desc = lc.MultiCalculationDescription(
    #    'my_BH("hole_spin").hole_mass',
    #    'my_BH("hole_spin").hole_spin',
    #    'Mvir')

    BH_mass, BH_spin, Mv = db.get_timestep("sim/ts1").gather_property('my_BH("hole_spin").(hole_mass, hole_spin)', 'Mvir')
    npt.assert_allclose(BH_mass, [100.,200.,300.])
    npt.assert_allclose(BH_spin, [900.,800.,700.])
    npt.assert_allclose(Mv, [1.,2.,3.])

    # despite being referred to twice, the my_BH function should only actually be called
    # once per halo. Otherwise the factorisation has been done wrong (and in particular,
    # a second call to the DB to retrieve the BH objects has been made, which could be
    # expensive)
    assert TestPathChoice.num_calls==3


def test_single_quotes():
    BH_mass, Mv = db.get_timestep("sim/ts1").gather_property("my_BH('hole_spin').hole_mass","Mvir")
    npt.assert_allclose(BH_mass, [100.,200.,300.])
    npt.assert_allclose(Mv, [1.,2.,3.])


def test_property_cascade():
    h = db.get_halo("sim/ts1/1")
    objs, = h.property_cascade("dbid()")
    assert len(objs)==3
    assert all([objs[i]==db.get_halo(x).id for i,x in enumerate(("sim/ts1/1", "sim/ts2/1", "sim/ts3/1"))])

def test_reverse_property_cascade():
    h = db.get_halo("sim/ts3/1")
    objs, = h.reverse_property_cascade("dbid()")
    assert len(objs)==3
    assert all([objs[i]==db.get_halo(x).id for i,x in enumerate(("sim/ts3/1", "sim/ts2/1", "sim/ts1/1"))])

def test_match_gather():
    ts1_halos, ts3_halos = db.get_timestep("sim/ts1").gather_property('dbid()','match("sim/ts3").dbid()')
    testing.assert_halolists_equal(ts1_halos, ['sim/ts1/1','sim/ts1/2','sim/ts1/3', 'sim/ts1/1.1'])
    testing.assert_halolists_equal(ts3_halos, ['sim/ts3/1','sim/ts3/2','sim/ts3/3', 'sim/ts3/1.1'])

def test_later():
    ts1_halos, ts3_halos = db.get_timestep("sim/ts1").gather_property('dbid()', 'later(2).dbid()')
    testing.assert_halolists_equal(ts1_halos, ['sim/ts1/1', 'sim/ts1/2', 'sim/ts1/3', 'sim/ts1/1.1'])
    testing.assert_halolists_equal(ts3_halos, ['sim/ts3/1', 'sim/ts3/2', 'sim/ts3/3', 'sim/ts3/1.1'])

def test_earlier():
    ts3_halos, ts1_halos = db.get_timestep("sim/ts3").gather_property('dbid()', 'earlier(2).dbid()')
    testing.assert_halolists_equal(ts1_halos, ['sim/ts1/1', 'sim/ts1/2', 'sim/ts1/3', 'sim/ts1/1.1'])
    testing.assert_halolists_equal(ts3_halos, ['sim/ts3/1', 'sim/ts3/2', 'sim/ts3/3', 'sim/ts3/1.1'])


def test_cascade_closes_connections():
    h = db.get_halo("sim/ts3/1")
    with db.testing.assert_connections_all_closed():
        h.reverse_property_cascade("Mvir")

def test_redirection_cascade_closes_connections():
    h = db.get_halo("sim/ts3/1")
    with db.testing.assert_connections_all_closed():
        h.reverse_property_cascade("my_BH('hole_spin').hole_mass")

def test_gather_closes_connections():
     with db.testing.assert_connections_all_closed():
        db.get_timestep("sim/ts1").gather_property('Mvir')