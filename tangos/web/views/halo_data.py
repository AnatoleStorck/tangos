import logging
import threading
import time
import warnings
from html import escape
from io import BytesIO

import matplotlib
import numpy as np
import pylab as p
from pyramid.response import Response
from pyramid.view import view_config

from ... import core
from ...config import (webview_cache_time, webview_default_image_format,
                       webview_plots_dpi)
from ...log import logger
from ...util.cache_dict import CacheDict
from . import halo_from_request, simulation_from_request, timestep_from_request

matplotlib.use('agg')

_matplotlib_lock = threading.RLock()

def sessionfree_lru_cache(num):
    """A drop-in replacement for functools.lru_cache that works with sqlalchemy ORM objects as first argument

    The purpose is to cache results of retrieving/calculating data from a database. However, such calculations
    rely on having an ORM object, which itself may change between calls because a different session is in use
    (e.g. if different threads are involved). This decorator roughly mimics the behaviour of functools.lru_cache,
    but keys on the .id attribute of the first argument, rather than the argument itself.
    """
    cache = CacheDict(cache_len=num)
    def f(func):
        def g(*args):
            key = type(args[0]),args[0].id, *args[1:]
            if key in cache:
                return cache[key]
            else:
                v = func(*args)
                cache[key] = v
                return v

        return g
    return f

def decode_property_name(name):
    name = name.replace("_slash_","/")
    return name

def format_array(data, max_array_length=3):
    if len(data)>max_array_length:
        return "Array"
    data_fmt = []
    for d in data:
        data_fmt.append(format_data(d))
    return "["+(", ".join(data_fmt))+"]"

def format_number(data):
    if np.issubdtype(type(data), np.integer):
        return "%d" % data
    elif np.issubdtype(type(data), np.floating):
        if abs(data) > 1e5 or abs(data) < 1e-2:
            return "%.2e" % data
        else:
            return "%.2f" % data
    else:
        warnings.warn("Formatting unknown number type")
        return str(data)

def format_data(data, request=None, relative_to=None, max_array_length=3):
    try:
        if hasattr(data,'__len__'):
            return format_array(data, max_array_length)
        elif np.issubdtype(type(data), np.number):
            return format_number(data)
        elif isinstance(data, core.SimulationObjectBase):
            return format_halo(data, request, relative_to)
        else:
            return escape(repr(data))
    except Exception as e:
        logging.exception("Exception in format_data")
        return str(e)



def _relative_description(this_halo, other_halo) :
    if other_halo is None :
        return "null"
    elif this_halo and this_halo.id==other_halo.id:
        return "this"
    elif this_halo and this_halo.timestep_id == other_halo.timestep_id :
        return "%s %d"%(other_halo.tag,other_halo.halo_number)
    elif this_halo and this_halo.timestep.simulation_id == other_halo.timestep.simulation_id :
        return "%s %d at t=%.2e Gyr"%(other_halo.tag,other_halo.halo_number, other_halo.timestep.time_gyr)
    else :
        if (not this_halo) or abs(this_halo.timestep.time_gyr - other_halo.timestep.time_gyr)>0.001:
            return "%s %d in %8s at t=%.2e Gyr"%(other_halo.tag,other_halo.halo_number, other_halo.timestep.simulation.basename,
                                                   other_halo.timestep.time_gyr)
        else:
            return "%s %d in %8s"%(other_halo.tag,other_halo.halo_number, other_halo.timestep.simulation.basename)


def format_halo(halo, request, relative_to=None):
    if relative_to==halo or request is None:
        return _relative_description(relative_to, halo)
    else:
        link = request.route_url('halo_view', simid=halo.timestep.simulation.escaped_basename,
                                 timestepid=halo.timestep.escaped_extension,
                                 halonumber=halo.basename)
        return "<a href='%s'>%s</a>"%(link, _relative_description(relative_to, halo))

def is_number(data):
    return np.issubdtype(type(data), np.number)

def can_use_elements_in_plot(data_array):
    if len(data_array)==0:
        return False
    else:
        return is_number(data_array[0])

def is_boolean(data):
    return np.issubdtype(type(data), np.bool_) and not np.issubdtype(type(data), np.number) and not hasattr(data,'__len__')

def can_use_elements_as_filter(data_array):
    if len(data_array)==0:
        return False
    else:
        return is_boolean(data_array[0])

def is_array(data):
    return isinstance(data, np.ndarray) and data.ndim>0

def elements_are_arrays(data_array):
    if len(data_array)==0:
        return False
    else:
        return is_array(data_array[0])


@view_config(route_name='calculate_all', renderer='json', http_cache=webview_cache_time)
def calculate_all(request):
    ts = timestep_from_request(request)
    typetag = request.matchdict['typetag']
    try:
        data, = ts.calculate_all(decode_property_name(request.matchdict['nameid']),
                                 sanitize=False, order_by_halo_number=True, object_type=typetag)
    except Exception as e:
        logging.exception("Exception in calculate_all")
        return {'error': getattr(e,'message',""), 'error_class': type(e).__name__}

    return {'timestep': ts.escaped_extension, 'data_formatted': [format_data(d, request) for d in data],
            'is_number': can_use_elements_in_plot(data),
            'is_boolean': can_use_elements_as_filter(data),
            'is_array': elements_are_arrays(data)}

@view_config(route_name='get_property', renderer='json', http_cache=webview_cache_time)
def get_property(request):
    halo = halo_from_request(request)
    property_name = decode_property_name(request.matchdict['nameid'])

    return get_property_data(halo, property_name, request)


def get_property_data(halo, property_name_or_result, request=None):
    if isinstance(property_name_or_result, str):
        try:
            result, p_info = _get_property_from_halo_and_name(halo, property_name_or_result)
            name = property_name_or_result
        except Exception as e:
            logging.exception("Exception in get_property_data")
            return {'error': getattr(e, 'message', ""), 'error_class': type(e).__name__}
    else:
        result = property_name_or_result.data_raw
        name = property_name_or_result.name.text

    return {'data_formatted': format_data(result, request, halo),
            'mini_language_query': name,
            'is_number': is_number(result),
            'is_boolean': is_boolean(result),
            'is_array': is_array(result)}


def start(request):
    p.ioff()
    p.figure(figsize=(float(request.GET.get('width',1000))/webview_plots_dpi,
                   float(request.GET.get('height',1000))/webview_plots_dpi))
    request.canvas = p.get_current_fig_manager().canvas


CONTENT_TYPES = {
    'png': 'image/png',
    'svg': 'image/svg+xml',
    'pdf': 'application/pdf'
}

def finish(request, getImage=True):
    extension = request.matchdict.get("ext", webview_default_image_format)
    print(f'Got extension: {extension}')
    if getImage:
        enter_finish_time = time.time()
        request.canvas.draw()
        draw_time = time.time()
        buffer = BytesIO()
        p.savefig(buffer, format=extension, dpi=webview_plots_dpi, bbox_inches='tight')
        end_time = time.time()

        logger.info(
            "Image rendering: matplotlib %.2fs; %s conversion %.3fs",
            draw_time - enter_finish_time,
            extension.upper(),
            end_time - draw_time
        )

    p.close()

    if getImage:
        try:
            r = Response(
                content_type=CONTENT_TYPES[extension],
                body=buffer.getvalue()
            )
            r.cache_expires(webview_cache_time)
            return r
        except KeyError:
            raise NotImplementedError(
                'Tangos does not support the provided image format: '
                f'{ext}. '
                'This can be changed in the config.'
            )


def rescale_plot(request):
    logx = request.GET.get('logx',False)
    logy = request.GET.get('logy',False)
    if logx and logy:
        p.loglog()
    elif logx:
        p.semilogx()
    elif logy:
        p.semilogy()

@view_config(route_name='gathered_plot')
def gathered_plot(request):
    start_time = time.time()
    name1, name2, v1, v2 = gathered_plot_data_from_request(request)
    logger.info("Gathering data took %.2fs"%(time.time()-start_time))
    with _matplotlib_lock:
        start(request)
        p.plot(v1,v2,'k.')
        p.xlabel(name1)
        p.ylabel(name2)
        rescale_plot(request)
        return finish(request)


@view_config(route_name='gathered_csv', renderer='csv')
def gathered_csv(request):
    name1, name2, v1, v2 = gathered_plot_data_from_request(request)
    return {
        'header': [name1, name2],
        'rows': np.array((v1,v2)).T,
        'name': "timestep_" + name1 + "_vs_" + name2
    }

def gathered_plot_data_from_request(request):
    ts = timestep_from_request(request)
    name1 = decode_property_name(request.matchdict['nameid1'])
    name2 = decode_property_name(request.matchdict['nameid2'])
    filter = decode_property_name(request.GET.get('filter', ""))
    object_typetag = request.GET.get('object_typetag', None)

    v1, v2 = _gathered_plot_data_from_parameters(ts, name1, name2, filter, object_typetag)

    return name1, name2, v1, v2

@sessionfree_lru_cache(100)
def _gathered_plot_data_from_parameters(ts, name1, name2, filter, object_typetag):
    if filter != "":
        v1, v2, f = ts.calculate_all(name1, name2, filter, object_typetag=object_typetag)
        v1 = v1[f]
        v2 = v2[f]
    else:
        v1, v2 = ts.calculate_all(name1, name2, object_typetag=object_typetag)
    return v1, v2


@view_config(route_name='cascade_plot')
def cascade_plot(request):
    name1, name2, v1, v2 = cascade_plot_data_from_request(request)
    with _matplotlib_lock:
        start(request)
        p.plot(v1,v2,'k')
        p.xlabel(name1)
        p.ylabel(name2)
        rescale_plot(request)
        return finish(request)

@view_config(route_name='cascade_csv', renderer='csv')
def cascade_csv(request):
    name1, name2, v1, v2 = cascade_plot_data_from_request(request)
    return {
        'header': [name1, name2],
        'rows': np.array((v1,v2)).T,
        'name': "timeseries_"+name1+"_vs_"+name2
    }

def cascade_plot_data_from_request(request):
    halo = halo_from_request(request)
    name1 = decode_property_name(request.matchdict['nameid1'])
    name2 = decode_property_name(request.matchdict['nameid2'])
    v1, v2 = _cascade_plot_data_from_parameters(halo, name1, name2)
    return name1, name2, v1, v2

@sessionfree_lru_cache(100)
def _cascade_plot_data_from_parameters(halo, name1, name2):
    v1, v2 = halo.calculate_for_progenitors(name1, name2)
    return v1, v2


def _sanitize_lims(val, absolute, data, default, log):
    if val is None:
        val = default
    val = float(val)

    if absolute:
        return val
    elif log:
        return np.nanpercentile(data[data>0], val)
    else:
        return np.nanpercentile(data, val)


def image_plot(request, data, property_info):
    log = request.GET.get('logimage', "0") == "1"
    vmin, vmax = (request.GET.get(_, None) for _ in ("vmin", "vmax"))
    cmap = request.GET.get("cmap", None)
    absolute = request.GET.get("absolute", "0") == "1"
    with _matplotlib_lock:
        start(request)

        if property_info:
            width = property_info.plot_extent()
        else:
            width = 1.0

        # This is required to properly use log norms with ranges larger than 10^7
        data = data.astype(np.float64)

        if data.ndim == 2:
            vmin = _sanitize_lims(vmin, absolute, data, 0, log)
            vmax = _sanitize_lims(vmax, absolute, data, 100, log)

            vmin, vmax = min(vmin, vmax), max(vmin, vmax)

        kwa = {"cmap": cmap}

        if log:
            kwa["norm"] = p.matplotlib.colors.LogNorm(vmin, vmax)
        else:
            kwa["norm"] = p.matplotlib.colors.Normalize(vmin, vmax)

        if width is not None:
            if hasattr(width, '__len__'):
                kwa["extent"] = width
            else:
                kwa["extent"] = (-width/2, width/2, -width/2, width/2)

        p.imshow(data, **kwa)

        if property_info:
            add_xy_labels(property_info, request)

        if data.ndim == 2:
            cb = p.colorbar()
            if property_info and property_info.plot_clabel() :
                cb.set_label(property_info.plot_clabel())

        return finish(request)


def add_xy_labels(property_info, request):
    p.xlabel(property_info.plot_xlabel())
    ylabel = property_info.plot_ylabel()
    # cludge follows - should be eliminated by fixing the mess around multi-name vs single-name property classes
    if not isinstance(ylabel, str):
        try:
            ylabel = ylabel[property_info.index_of_name(decode_property_name(request.matchdict['nameid']))]
        except:
            ylabel = ""
    p.ylabel(ylabel)


@view_config(route_name='array_plot')
def array_plot(request):
    halo = halo_from_request(request)
    name = decode_property_name(request.matchdict['nameid'])

    val, property_info = _get_property_from_halo_and_name(halo, name)

    if len(val.shape)>1:
        return image_plot(request, val, property_info)

    with _matplotlib_lock:
        start(request)

        p.plot(property_info.plot_x_values(val),val)

        if property_info.plot_xlog() and property_info.plot_ylog():
            p.loglog()
        elif property_info.plot_xlog():
            p.semilogx()
        elif property_info.plot_ylog():
            p.semilogy()


        if property_info.plot_yrange():
            p.ylim(*property_info.plot_yrange())

        add_xy_labels(property_info, request)

        return finish(request)

@sessionfree_lru_cache(100)
def _get_property_from_halo_and_name(halo, name):
    return halo.calculate(name, True)

@view_config(route_name='array_csv', renderer='csv')
def array_csv(request):
    halo = halo_from_request(request)
    name = decode_property_name(request.matchdict['nameid'])
    val, property_info = halo.calculate(name, True)
    xval = property_info.plot_x_values(val)

    return {
        'header': ["bin_center", name],
        'rows': np.array((xval,val)).T,
    }
