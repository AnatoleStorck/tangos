from pyramid.view import view_config
import pyramid.httpexceptions as exc
import tangos

def halo_later_earlier(request, rel='later'):
    sim = tangos.get_simulation(request.matchdict['simid'], request.dbsession)
    ts = tangos.get_timestep(request.matchdict['timestepid'], request.dbsession, sim)
    halo = ts.halos.filter_by(halo_number=request.matchdict['halonumber']).first()
    steps = int(request.matchdict['n'])

    if steps==0:
        return

    halo = halo.calculate("%s(%d)"%(rel,steps))

    raise exc.HTTPFound(request.route_url("halo_view", simid=halo.timestep.simulation.basename,
                                          timestepid=halo.timestep.extension,
                                          halonumber=halo.halo_number))


@view_config(route_name='halo_later', renderer=None)
def halo_later(request):
    return halo_later_earlier(request, 'later')


@view_config(route_name='halo_earlier', renderer=None)
def halo_earlier(request):
    return halo_later_earlier(request, 'earlier')
