from contextlib import AbstractContextManager
from pathlib import Path
from .rawdata import *
import h5py
import py4vasp.exceptions as exception


class File(AbstractContextManager):
    """Extract raw data from the HDF5 file.

    This class opens a given HDF5 file and its functions then provide access to
    the raw data via dataclasses. When you request the dataclass for a certain
    quantity, this class will generate the necessary pointers to the relevant
    HDF5 datasets, which can then be accessed like numpy arrays.

    This class also extends a context manager so it can be used to automatically
    deal with closing the HDF5 file. You cannot access the data in the
    dataclasses after you closed the HDF5 file.

    Parameters
    ----------
    filename : str or Path
        Name of the file from which the data is read (defaults to default_filename).

    Notes
    -----
    Except for scalars this class does not actually load the data from file. It
    only creates a pointer to the correct position in the HDF5 file. So you need
    to extract the data before closing the file. This lazy loading significantly
    enhances the performance if you are only interested in a subset of the data.
    """

    default_filename = "vaspout.h5"
    "Name of the HDF5 file Vasp creates."

    def __init__(self, filename=None):
        filename = self._actual_filename(filename)
        self.closed = False
        try:
            self._h5f = h5py.File(filename, "r")
        except OSError as err:
            error_message = (
                f"Error opening {filename} to read the data. Please check that you "
                "already completed the Vasp calculation and that the file is indeed "
                "in the directory. Please also check whether you are running the "
                "Python script in the same directory or pass the appropriate filename "
                "including the path."
            )
            raise exception.FileAccessError(error_message) from err

    def _actual_filename(self, filename):
        if filename is None:
            return File.default_filename
        elif Path(filename).is_dir():
            return Path(filename) / File.default_filename
        else:
            return filename

    def version(self):
        """Read the version number of Vasp.

        Returns
        -------
        RawVersion
            The major, minor, and patch number of Vasp.
        """
        self._raise_error_if_closed()
        return RawVersion(
            major=self._h5f["version/major"][()],
            minor=self._h5f["version/minor"][()],
            patch=self._h5f["version/patch"][()],
        )

    def dos(self):
        """Read the electronic density of states (Dos).

        Returns
        -------
        RawDos or None
            A list of energies E and the associated raw electronic Dos D(E). The
            energies need to be manually shifted to the Fermi energy. If
            available, the projections on a set of projectors are included.
        """
        self._raise_error_if_closed()
        if "results/electron_dos/energies" not in self._h5f:
            return None
        return RawDos(
            version=self.version(),
            fermi_energy=self._h5f["results/electron_dos/efermi"][()],
            energies=self._h5f["results/electron_dos/energies"],
            dos=self._h5f["results/electron_dos/dos"],
            projectors=self.projectors(),
            projections=self._safe_get_key("results/electron_dos/dospar"),
        )

    def band(self):
        """Read the band structure generated by Vasp.

        Returns
        -------
        RawBand
            The raw electronic eigenvalues at the specific **k** points. These
            values need to be manually aligned to the Fermi energy if desired.
            If available the projections on a set of projectors are included.
        """
        self._raise_error_if_closed()
        return RawBand(
            version=self.version(),
            fermi_energy=self._h5f["results/electron_dos/efermi"][()],
            kpoints=self.kpoints(),
            eigenvalues=self._h5f["results/electron_eigenvalues/eigenvalues"],
            projectors=self.projectors(),
            projections=self._safe_get_key("results/projectors/par"),
        )

    def topology(self):
        """Read the topology data used in the Vasp calculation.

        Returns
        -------
        RawTopology
            Contains the information which ion types were used and how many ions
            of each type there are.
        """
        self._raise_error_if_closed()
        return RawTopology(
            version=self.version(),
            ion_types=self._h5f["results/positions/ion_types"],
            number_ion_types=self._h5f["results/positions/number_ion_types"],
        )

    def trajectory(self):
        """Read the trajectory data of an ionic relaxation or MD simulation.

        Returns
        -------
        RawTrajectory
            Contains the topology of the crystal and the position of all atoms
            and the shape of the unit cell for all ionic steps.
        """
        self._raise_error_if_closed()
        return RawTrajectory(
            version=self.version(),
            topology=self.topology(),
            positions=self._h5f["intermediate/ion_dynamics/position_ions"],
            lattice_vectors=self._h5f["intermediate/ion_dynamics/lattice_vectors"],
        )

    def projectors(self):
        """Read the projectors information if present.

        Returns
        -------
        RawProjectors or None
            If Vasp was set to produce the orbital decomposition of the bands
            the associated projector information is returned.
        """
        self._raise_error_if_closed()
        if "results/projectors" not in self._h5f:
            return None
        return RawProjectors(
            version=self.version(),
            topology=self.topology(),
            orbital_types=self._h5f["results/projectors/lchar"],
            number_spins=self._h5f["results/electron_eigenvalues/ispin"][()],
        )

    def kpoints(self):
        """Read the **k** points at which Vasp evaluated the wave functions.

        Returns
        -------
        RawKpoints
            In addition to the coordinates of the **k** points and the cell
            information, we include some information given in the input file
            about the generation and labels of the **k** points, which may be
            useful for band structures.
        """
        self._raise_error_if_closed()
        return RawKpoints(
            version=self.version(),
            mode=self._h5f["input/kpoints/mode"][()],
            number=self._h5f["input/kpoints/number_kpoints"][()],
            coordinates=self._h5f["results/electron_eigenvalues/kpoint_coords"],
            weights=self._h5f["results/electron_eigenvalues/kpoints_symmetry_weight"],
            labels=self._safe_get_key("input/kpoints/labels_kpoints"),
            label_indices=self._safe_get_key("input/kpoints/positions_labels_kpoints"),
            cell=self.cell(),
        )

    def cell(self):
        """Read the unit cell information of the crystal.

        Returns
        -------
        RawCell
            The lattice vectors of the unit cell scaled by a constant factor.
        """
        self._raise_error_if_closed()
        return RawCell(
            version=self.version(),
            scale=self._h5f["results/positions/scale"][()],
            lattice_vectors=self._h5f["results/positions/lattice_vectors"],
        )

    def magnetism(self):
        """Read the magnetisation data of the crystal.

        Returns
        -------
        RawMagnetism
            The magnetic moments and charges on every atom in orbital resolved
            representation.
        """
        self._raise_error_if_closed()
        key = "intermediate/ion_dynamics/magnetism/moments"
        if key not in self._h5f:
            return None
        return RawMagnetism(version=self.version(), moments=self._h5f[key])

    def structure(self):
        """Read the structure information.

        Returns
        -------
        RawStructure
            The unit cell, position of the atoms and magnetic moments.
        """
        self._raise_error_if_closed()
        return RawStructure(
            version=self.version(),
            topology=self.topology(),
            cell=self.cell(),
            positions=self._h5f["results/positions/position_ions"],
            magnetism=self.magnetism(),
        )

    def energy(self):
        """Read the energies during the ionic convergence.

        Returns
        -------
        RawEnergy
            Information about different energies for every step in the relaxation
            or MD simulation.
        """
        self._raise_error_if_closed()
        return RawEnergy(
            version=self.version(),
            labels=self._h5f["intermediate/ion_dynamics/energies_tags"],
            values=self._h5f["intermediate/ion_dynamics/energies"],
        )

    def density(self):
        """Read the charge and potentially magnetization density.

        Returns
        -------
        RawDensity
            The density is represented on the Fourier grid in the unit cell.
        """
        self._raise_error_if_closed()
        return RawDensity(
            version=self.version(),
            structure=self.structure(),
            charge=self._h5f["charge/charge"],
        )

    def close(self):
        "Close the associated HDF5 file (automatically if used as context manager)."
        self._h5f.close()
        self.closed = True

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _raise_error_if_closed(self):
        if self.closed:
            raise exception.FileAccessError("I/O operation on closed file.")

    def _safe_get_key(self, key):
        if key in self._h5f:
            return self._h5f[key]
        else:
            return None
