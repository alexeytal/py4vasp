from py4vasp.data import _util
from py4vasp.data._base import DataBase, RefinementDescriptor
import py4vasp.exceptions as exception
import numpy as np
import functools


class Magnetism(DataBase):
    """The evolution of the magnetization over the simulation.

    This class gives access to the magnetic moments and charges projected on the
    different orbitals on every atom.

    Parameters
    ----------
    raw_magnetism : RawMagnetism
        Dataclass containing the charges and magnetic moments read from Vasp.
    """

    _missing_data_message = "Atom resolved magnetic information not present, please verify LORBIT tag is set."

    to_dict = RefinementDescriptor("_to_dict")
    read = RefinementDescriptor("_to_dict")
    charges = RefinementDescriptor("_charges")
    moments = RefinementDescriptor("_moments")
    total_charges = RefinementDescriptor("_total_charges")
    total_moments = RefinementDescriptor("_total_moments")
    __str__ = RefinementDescriptor("_to_string")


def _to_string(raw_magnetism):
    magmom = "MAGMOM = "
    moments_last_step = _total_moments(raw_magnetism, -1)
    moments_to_string = lambda vec: " ".join(f"{moment:.2f}" for moment in vec)
    if moments_last_step is None:
        return "not available"
    elif moments_last_step.ndim == 1:
        return magmom + moments_to_string(moments_last_step)
    else:
        separator = " \\\n         "
        generator = (moments_to_string(vec) for vec in moments_last_step)
        return magmom + separator.join(generator)


_step_parameter = """Parameters
----------
steps : int or range
    If present specifies which steps of the simulation should be extracted.
    By default the data of all steps is read.
"""

_index_note = """Notes
-----
The index order is different compared to the raw data when noncollinear calculations
are used. This routine returns the magnetic moments as (steps, atoms, orbitals,
directions)."""


@_util.add_doc(
    f"""Read the charges and magnetization data into a dictionary.

{_step_parameter}

Returns
-------
dict
    Contains the charges and magnetic moments generated by Vasp projected
    on atoms and orbitals.

{_index_note}"""
)
def _to_dict(raw_magnetism, steps=None):
    moments = _moments(raw_magnetism, steps)
    moments = {"moments": moments} if moments is not None else {}
    return {"charges": _charges(raw_magnetism, steps), **moments}


@_util.add_doc(
    f"""Read the charges of the selected steps.

{_step_parameter}

Returns
-------
np.ndarray
    Contains the charges for the selected steps projected on atoms and orbitals."""
)
def _charges(raw_magnetism, steps=None):
    moments = _Magnetism(raw_magnetism.moments)
    steps = _default_steps_if_none(moments, steps)
    return moments[steps, 0, :, :]


@_util.add_doc(
    f"""Read the magnetic moments of the selected steps.

{_step_parameter}

Returns
-------
np.ndarray
    Contains the magnetic moments for the selected steps projected on atoms and
    orbitals.

{_index_note}"""
)
def _moments(raw_magnetism, steps=None):
    moments = _Magnetism(raw_magnetism.moments)
    steps = _default_steps_if_none(moments, steps)
    if moments.shape[1] == 1:
        return None
    elif moments.shape[1] == 2:
        return moments[steps, 1, :, :]
    else:
        moments = moments[steps, 1:, :, :]
        direction_axis = 1 if moments.ndim == 4 else 0
        return np.moveaxis(moments, direction_axis, -1)


@_util.add_doc(
    f"""Read the total charges of the selected steps.

{_step_parameter}

Returns
-------
np.ndarray
    Contains the total charges for the selected steps projected on atoms. This
    corresponds to the charges summed over the orbitals."""
)
def _total_charges(raw_magnetism, steps=None):
    return _sum_over_orbitals(_charges(raw_magnetism, steps))


@_util.add_doc(
    f"""Read the total magnetic moments of the selected steps.

{_step_parameter}

Returns
-------
np.ndarray
    Contains the total magnetic moments for the selected steps projected on atoms.
    This corresponds to the magnetic moments summed over the orbitals."""
)
def _total_moments(raw_magnetism, steps=None):
    moments = _Magnetism(raw_magnetism.moments)
    if moments.shape[1] == 1:
        return None
    elif moments.shape[1] == 2:
        return _sum_over_orbitals(_moments(raw_magnetism, steps))
    else:
        steps = _default_steps_if_none(moments, steps)
        total_moments = _sum_over_orbitals(moments[steps, 1:, :, :])
        direction_axis = 1 if total_moments.ndim == 3 else 0
        return np.moveaxis(total_moments, direction_axis, -1)


class _Magnetism(_util.Reader):
    def error_message(self, key, err):
        return (
            f"Error reading the magnetic moments. Please check if the key "
            f"`{key[0]}` is properly formatted and within the boundaries. "
            "Additionally, you may consider the original error message:\n" + err.args[0]
        )


def _default_steps_if_none(moments, steps):
    return steps if steps is not None else range(len(moments))


def _sum_over_orbitals(quantity):
    return np.sum(quantity, axis=-1)
