# -*- coding: utf-8 -*-
"""
Ephemeris calculations using SunPy coordinate frames
"""
import datetime
import warnings

import numpy as np
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import (SkyCoord, Angle, Longitude,
                                 ICRS, PrecessedGeocentric, AltAz,
                                 get_body_barycentric)
from astropy.coordinates.representation import CartesianRepresentation, SphericalRepresentation
from astropy._erfa.core import ErfaWarning
from astropy.constants import c as speed_of_light
# Versions of Astropy that do not have HeliocentricMeanEcliptic have the same frame
# with the incorrect name HeliocentricTrueEcliptic
try:
    from astropy.coordinates import HeliocentricMeanEcliptic
except ImportError:
    from astropy.coordinates import HeliocentricTrueEcliptic as HeliocentricMeanEcliptic

from sunpy.time import parse_time
from sunpy import log

from .frames import HeliographicStonyhurst as HGS
from .transformations import _SUN_DETILT_MATRIX

__all__ = ['get_body_heliographic_stonyhurst', 'get_earth',
           'get_sun_B0', 'get_sun_L0', 'get_sun_P', 'get_sunearth_distance',
           'get_sun_orientation', 'get_horizons_coord']


def get_body_heliographic_stonyhurst(body, time='now', observer=None):
    """
    Return a `~sunpy.coordinates.frames.HeliographicStonyhurst` frame for the location of a
    solar-system body at a specified time.

    Parameters
    ----------
    body : `str`
        The solar-system body for which to calculate positions
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format
    observer : `~astropy.coordinates.SkyCoord`
        If not None, the returned coordinate is the apparent location (i.e., accounts for light
        travel time)

    Returns
    -------
    out : `~sunpy.coordinates.frames.HeliographicStonyhurst`
        Location of the solar-system body in the `~sunpy.coordinates.HeliographicStonyhurst` frame
    """
    obstime = parse_time(time)

    if observer is None:
        body_icrs = get_body_barycentric(body, obstime)
    else:
        observer_icrs = SkyCoord(observer).icrs.cartesian

        # This implementation is modeled after Astropy's `_get_apparent_body_position`
        light_travel_time = 0.*u.s
        emitted_time = obstime
        delta_light_travel_time = 1.*u.s  # placeholder value
        while np.any(np.fabs(delta_light_travel_time) > 1.0e-8*u.s):
            body_icrs = get_body_barycentric(body, emitted_time)
            distance = (body_icrs - observer_icrs).norm()
            delta_light_travel_time = light_travel_time - distance / speed_of_light
            light_travel_time = distance / speed_of_light
            emitted_time = obstime - light_travel_time

        log.info(f"Apparent body location accounts for {light_travel_time.to('s').value:.2f}"
                  " seconds of light travel time")

    body_hgs = ICRS(body_icrs).transform_to(HGS(obstime=obstime))

    return body_hgs


def get_earth(time='now'):
    """
    Return a `~astropy.coordinates.SkyCoord` for the location of the Earth at a specified time in
    the `~sunpy.coordinates.frames.HeliographicStonyhurst` frame.  The longitude will be 0 by definition.

    Parameters
    ----------
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format

    Returns
    -------
    out : `~astropy.coordinates.SkyCoord`
        Location of the Earth in the `~sunpy.coordinates.frames.HeliographicStonyhurst` frame
    """
    earth = get_body_heliographic_stonyhurst('earth', time=time)

    # Explicitly set the longitude to 0
    earth = SkyCoord(0*u.deg, earth.lat, earth.radius, frame=earth)

    return earth


def get_sun_B0(time='now'):
    """
    Return the B0 angle for the Sun at a specified time, which is the heliographic latitude of the
    Sun-disk center as seen from Earth.  The range of B0 is +/-7.23 degrees.

    Parameters
    ----------
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format

    Returns
    -------
    out : `~astropy.coordinates.Angle`
        The position angle
    """
    return Angle(get_earth(time).lat)


# Ignore warnings that result from going back in time to the first Carrington rotation
with warnings.catch_warnings():
    warnings.simplefilter("ignore", ErfaWarning)

    # Carrington rotation 1 starts late in the day on 1853 Nov 9
    # according to Astronomical Algorithms (Meeus 1998, p.191)
    _time_first_rotation = Time('1853-11-09 21:36')

    # Longitude of Earth at Carrington rotation 1 in de-tilted HCRS (so that solar north pole is Z)
    _lon_first_rotation = \
        get_earth(_time_first_rotation).hcrs.cartesian.transform(_SUN_DETILT_MATRIX) \
        .represent_as(SphericalRepresentation).lon.to('deg')


def get_sun_L0(time='now'):
    """
    Return the L0 angle for the Sun at a specified time, which is the Carrington longitude of the
    Sun-disk center as seen from Earth.

    .. warning::
       Due to apparent disagreement between published references, the returned L0 may be inaccurate
       by up to ~2 arcmin, which translates in the worst case to a shift of ~0.5 arcsec in
       helioprojective coordinates for an observer at 1 AU.  Until this is resolved, be cautious
       with analysis that depends critically on absolute (as opposed to relative) values of
       Carrington longitude.

    Parameters
    ----------
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format

    Returns
    -------
    out : `~astropy.coordinates.Longitude`
        The Carrington longitude
    """
    obstime = parse_time(time)

    # Calculate the longitude due to the Sun's rotation relative to the stars
    # A sidereal rotation is defined to be exactly 25.38 days
    sidereal_lon = Longitude((obstime.jd - _time_first_rotation.jd) / 25.38 * 360*u.deg)

    # Calculate the longitude of the Earth in de-tilted HCRS
    lon_obstime = get_earth(obstime).hcrs.cartesian.transform(_SUN_DETILT_MATRIX) \
                  .represent_as(SphericalRepresentation).lon.to('deg')

    return Longitude(lon_obstime - _lon_first_rotation - sidereal_lon)


def get_sun_P(time='now'):
    """
    Return the position (P) angle for the Sun at a specified time, which is the angle between
    geocentric north and solar north as seen from Earth, measured eastward from geocentric north.
    The range of P is +/-26.3 degrees.

    Parameters
    ----------
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format

    Returns
    -------
    out : `~astropy.coordinates.Angle`
        The position angle
    """
    obstime = parse_time(time)

    # Define the frame where its Z axis is aligned with geocentric north
    geocentric = PrecessedGeocentric(equinox=obstime, obstime=obstime)

    return _sun_north_angle_to_z(geocentric)


def get_sunearth_distance(time='now'):
    """
    Return the distance between the Sun and the Earth at a specified time.

    Parameters
    ----------
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format

    Returns
    -------
    out : `~astropy.coordinates.Distance`
        The Sun-Earth distance
    """
    return get_earth(time).radius


def get_sun_orientation(location, time='now'):
    """
    Return the orientation angle for the Sun from a specified Earth location and time.  The
    orientation angle is the angle between local zenith and solar north, measured eastward from
    local zenith.

    Parameters
    ----------
    location : `~astropy.coordinates.EarthLocation`
        Observer location on Earth
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format

    Returns
    -------
    out : `~astropy.coordinates.Angle`
        The orientation of the Sun
    """
    obstime = parse_time(time)

    # Define the frame where its Z axis is aligned with local zenith
    local_frame = AltAz(obstime=obstime, location=location)

    return _sun_north_angle_to_z(local_frame)


def _sun_north_angle_to_z(frame):
    """
    Return the angle between solar north and the Z axis of the provided frame's coordinate system
    and observation time.
    """
    # Find the Sun center in HGS at the frame's observation time(s)
    sun_center_repr = SphericalRepresentation(0*u.deg, 0*u.deg, 0*u.km)
    # The representation is repeated for as many times as are in obstime prior to transformation
    sun_center = SkyCoord(sun_center_repr._apply('repeat', frame.obstime.size),
                          frame=HGS, obstime=frame.obstime)

    # Find the Sun north in HGS at the frame's observation time(s)
    # Only a rough value of the solar radius is needed here because, after the cross product,
    #   only the direction from the Sun center to the Sun north pole matters
    sun_north_repr = SphericalRepresentation(0*u.deg, 90*u.deg, 690000*u.km)
    # The representation is repeated for as many times as are in obstime prior to transformation
    sun_north = SkyCoord(sun_north_repr._apply('repeat', frame.obstime.size),
                         frame=HGS, obstime=frame.obstime)

    # Find the Sun center and Sun north in the frame's coordinate system
    sky_normal = sun_center.transform_to(frame).data.to_cartesian()
    sun_north = sun_north.transform_to(frame).data.to_cartesian()

    # Use cross products to obtain the sky projections of the two vectors (rotated by 90 deg)
    sun_north_in_sky = sun_north.cross(sky_normal)
    z_in_sky = CartesianRepresentation(0, 0, 1).cross(sky_normal)

    # Normalize directional vectors
    sky_normal /= sky_normal.norm()
    sun_north_in_sky /= sun_north_in_sky.norm()
    z_in_sky /= z_in_sky.norm()

    # Calculate the signed angle between the two projected vectors
    cos_theta = sun_north_in_sky.dot(z_in_sky)
    sin_theta = sun_north_in_sky.cross(z_in_sky).dot(sky_normal)
    angle = np.arctan2(sin_theta, cos_theta).to('deg')

    # If there is only one time, this function's output should be scalar rather than array
    if angle.size == 1:
        angle = angle[0]

    return Angle(angle)


def get_horizons_coord(body, time='now', id_type='majorbody'):
    """
    Queries JPL HORIZONS and returns a `~astropy.coordinates.SkyCoord` for the location of a
    solar-system body at a specified time.  This function requires the Astroquery package to
    be installed and requires Internet access.

    Parameters
    ----------
    body : `str`
        The solar-system body for which to calculate positions
    id_type : `str`
        If 'majorbody', search by name for planets or satellites.  If 'id', search by ID number.
    time : various
        Time to use as `~astropy.time.Time` or in a parse_time-compatible format

    Returns
    -------
    out : `~astropy.coordinates.SkyCoord`
        Location of the solar-system body

    Notes
    -----
    Be aware that there can be discrepancies between the coordinates returned by JPL HORIZONS,
    the coordinates reported in mission data files, and the coordinates returned by
    `~sunpy.coordinates.get_body_heliographic_stonyhurst()`.

    References
    ----------
    * `JPL HORIZONS <https://ssd.jpl.nasa.gov/?horizons>`_
    * `Astroquery <https://astroquery.readthedocs.io/en/latest/>`_

    Examples
    --------
    >>> from sunpy.coordinates import get_horizons_coord

    Query the location of Venus

    >>> get_horizons_coord('Venus barycenter', '2001-02-03 04:05:06')  # doctest: +REMOTE_DATA
    INFO: Obtained JPL HORIZONS location for Venus Barycenter (2) [sunpy.coordinates.ephemeris]
    <SkyCoord (HeliographicStonyhurst: obstime=2001-02-03T04:05:06.000): (lon, lat, radius) in (deg, deg, AU)
        (326.06844114, -1.64998481, 0.71915147)>

    Query the location of the SDO spacecraft

    >>> get_horizons_coord('SDO', '2011-11-11 11:11:11')  # doctest: +REMOTE_DATA
    INFO: Obtained JPL HORIZONS location for Solar Dynamics Observatory (spac [sunpy.coordinates.ephemeris]
    <SkyCoord (HeliographicStonyhurst: obstime=2011-11-11T11:11:11.000): (lon, lat, radius) in (deg, deg, AU)
        (0.01018888, 3.29640407, 0.99011042)>

    Query the location of the SOHO spacecraft via its ID number (-21)

    >>> get_horizons_coord(-21, '2004-05-06 11:22:33', 'id')  # doctest: +REMOTE_DATA
    INFO: Obtained JPL HORIZONS location for SOHO (spacecraft) (-21) [sunpy.coordinates.ephemeris]
    <SkyCoord (HeliographicStonyhurst: obstime=2004-05-06T11:22:33.000): (lon, lat, radius) in (deg, deg, AU)
        (0.2523461, -3.55863351, 0.99923086)>
    """
    obstime = parse_time(time)

    # Import here so that astroquery is not a module-level dependency
    from astroquery.jplhorizons import Horizons
    query = Horizons(id=body, id_type=id_type,
                     location='500@10',      # Heliocentric (mean ecliptic)
                     epochs=obstime.tdb.jd)  # Time must be provided in JD TDB
    try:
        result = query.vectors()
    except:  # Catch and re-raise all exceptions, and also provide query URL if generated
        if query.uri is not None:
            log.error(f"See the raw output from the JPL HORIZONS query at {query.uri}")
        raise
    log.info(f"Obtained JPL HORIZONS location for {result[0]['targetname']}")

    vector = CartesianRepresentation(result[0]['x', 'y', 'z'])*u.AU
    coord = SkyCoord(vector, frame=HeliocentricMeanEcliptic, obstime=obstime)

    return coord.transform_to(HGS)
