from contextlib import AbstractContextManager
from pathlib import Path
from .rawdata import *
import h5py
import py4vasp.exceptions as exception
import py4vasp._util.version as _version


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
        self._path = Path(filename).resolve().parent
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

    @property
    def path(self):
        return self._path

    @property
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

    @property
    def system(self):
        """Read the system tag provided in the INCAR file.

        Returns
        -------
        DataDict[str, RawSystem]
            Contains the name of the system.
        """
        return self._make_data_dict(self._read_system())

    def _read_system(self):
        self._raise_error_if_closed()
        return RawSystem(self._h5f["input/incar/SYSTEM"][()])

    @property
    def dos(self):
        """Read all the electronic density of states (Dos) information.

        Returns
        -------
        DataDict[str, RawDos or None]
            The key of the dictionary specifies the kind of the Dos. The value
            contains  list of energies E and the associated raw electronic Dos
            D(E). The energies need to be manually shifted to the Fermi energy.
            If available, the projections on a set of projectors are included.
        """
        return self._make_data_dict(
            self._read_dos(), kpoints_opt=self._read_dos("_kpoints_opt")
        )

    def _read_dos(self, suffix=""):
        self._raise_error_if_closed()
        if f"results/electron_dos{suffix}/energies" not in self._h5f:
            return None
        return RawDos(
            fermi_energy=self._h5f[f"results/electron_dos{suffix}/efermi"][()],
            energies=self._h5f[f"results/electron_dos{suffix}/energies"],
            dos=self._h5f[f"results/electron_dos{suffix}/dos"],
            projectors=self._read_projector(suffix),
            projections=self._safe_get_key(f"results/electron_dos{suffix}/dospar"),
        )

    @property
    def band(self):
        """Read all the band structures generated by Vasp.

        Returns
        -------
        DataDict[str, RawBand or None]
            The key of the dictionary specifies the kind of the band structure.
            The value contains the raw electronic eigenvalues at the specific
            **k** points. These values need to be manually aligned to the Fermi
            energy if desired. If available the projections on a set of
            projectors are included.
        """
        return self._make_data_dict(
            self._read_band(), kpoints_opt=self._read_band("_kpoints_opt")
        )

    def _read_band(self, suffix=""):
        self._raise_error_if_closed()
        if f"results/electron_eigenvalues{suffix}" not in self._h5f:
            return None
        return RawBand(
            fermi_energy=self._h5f[f"results/electron_dos{suffix}/efermi"][()],
            kpoints=self._read_kpoint(suffix),
            eigenvalues=self._h5f[f"results/electron_eigenvalues{suffix}/eigenvalues"],
            occupations=self._h5f[f"results/electron_eigenvalues{suffix}/fermiweights"],
            projectors=self._read_projector(suffix),
            projections=self._safe_get_key(f"results/projectors{suffix}/par"),
        )

    @property
    def topology(self):
        """Read all the topology data used in the Vasp calculation.

        Returns
        -------
        DataDict[str, RawTopology]
            The key of the dictionary contains information about the kind of the
            topology. The value contains the information which ion types were
            used and how many ions of each type there are.
        """
        return self._make_data_dict(self._read_topology())

    def _read_topology(self):
        self._raise_error_if_closed()
        return RawTopology(
            ion_types=self._h5f["results/positions/ion_types"],
            number_ion_types=self._h5f["results/positions/number_ion_types"],
        )

    @property
    def projector(self):
        """Read all the information about projectors if present.

        Returns
        -------
        DataDict[str, RawProjector or None]
            If Vasp was set to produce the orbital decomposition of the bands
            the associated projector information is returned. The key specifies
            which kind of projectors are returned, the value lists the topology,
            the orbital types and the number of spins.
        """
        return self._make_data_dict(
            self._read_projector(), kpoints_opt=self._read_projector("_kpoints_opt")
        )

    def _read_projector(self, suffix=""):
        self._raise_error_if_closed()
        if f"results/projectors{suffix}" not in self._h5f:
            return None
        eigenvalues_key = f"results/electron_eigenvalues{suffix}/eigenvalues"
        return RawProjector(
            topology=self._read_topology(),
            orbital_types=self._h5f[f"results/projectors{suffix}/lchar"],
            number_spins=len(self._h5f[eigenvalues_key]),
        )

    @property
    def kpoint(self):
        """Read all the **k** points at which Vasp evaluated the orbitals
        and eigenvalues.

        Returns
        -------
        DataDict[str, RawKpoint or None]
            The key of the dictionary specifies the kind of the **k** point
            grid. For the value, the coordinates of the **k** points and the
            cell information is returned. Added is some information given in
            the input file about the generation and labels of the **k** points,
            which may be useful for band structures.
        """
        return self._make_data_dict(
            self._read_kpoint(), kpoints_opt=self._read_kpoint("_kpoints_opt")
        )

    def _read_kpoint(self, suffix=""):
        self._raise_error_if_closed()
        input = f"input/kpoints_opt" if suffix == "_kpoints_opt" else "input/kpoints"
        result = f"results/electron_eigenvalues{suffix}"
        if input not in self._h5f or result not in self._h5f:
            return None
        return RawKpoint(
            mode=self._h5f[f"{input}/mode"][()].decode(),
            number=self._h5f[f"{input}/number_kpoints"][()],
            coordinates=self._h5f[f"{result}/kpoint_coords"],
            weights=self._h5f[f"{result}/kpoints_symmetry_weight"],
            labels=self._safe_get_key(f"{input}/labels_kpoints"),
            label_indices=self._safe_get_key(f"{input}/positions_labels_kpoints"),
            cell=self._read_cell(),
        )

    @property
    def cell(self):
        """Read all the unit cell information of the crystal.

        Returns
        -------
        DataDict[str, RawCell]
            The key of the dictionary specified the kind of the unit cell.
            The value contains the lattice vectors of the unit cell and a
            scaling factor.
        """
        return self._make_data_dict(self._read_cell())

    def _read_cell(self):
        self._raise_error_if_closed()
        return RawCell(
            scale=self._h5f["results/positions/scale"][()],
            lattice_vectors=self._h5f["/intermediate/ion_dynamics/lattice_vectors"],
        )

    @property
    def magnetism(self):
        """Read all the magnetization data of the crystal.

        Returns
        -------
        DataDict[str, RawMagnetism]
            The key specifies the kind of magnetization data and the value
            containes the magnetic moments and charges on every atom in orbital
            resolved representation. Structural information is added for
            convenient plotting.
        """
        return self._make_data_dict(self._read_magnetism())

    def _read_magnetism(self):
        self._raise_error_if_closed()
        key = "intermediate/ion_dynamics/magnetism/moments"
        if key not in self._h5f:
            return None
        return RawMagnetism(structure=self._read_structure(), moments=self._h5f[key])

    @property
    def structure(self):
        """Read all the structural information.

        Returns
        -------
        DataDict[str, RawStructure]
            The key of the dictionary specifies the kind of the structure.
            The value contains the unit cell and the position of all the atoms.
        """
        return self._make_data_dict(self._read_structure())

    def _read_structure(self):
        self._raise_error_if_closed()
        return RawStructure(
            topology=self._read_topology(),
            cell=self._read_cell(),
            positions=self._h5f["intermediate/ion_dynamics/position_ions"],
        )

    @property
    def energy(self):
        """Read all the energies during the ionic convergence.

        Returns
        -------
        DataDict[str, RawEnergy]
            The key of the dictionary specifies the kind of energy contained.
            The value contains a label for all energies and the values for
            every step in the relaxation or MD simulation.
        """
        return self._make_data_dict(self._read_energy())

    def _read_energy(self):
        self._raise_error_if_closed()
        return RawEnergy(
            labels=self._h5f["intermediate/ion_dynamics/energies_tags"],
            values=self._h5f["intermediate/ion_dynamics/energies"],
        )

    @property
    def density(self):
        """Read the charge and potentially magnetization density.

        Returns
        -------
        DataDict[str, RawDensity]
            The key informs about the kind of density reported. The value
            represents the density on the Fourier grid in the unit cell.
            Structural information is added for convenient plotting.
        """
        return self._make_data_dict(self._read_density())

    def _read_density(self):
        self._raise_error_if_closed()
        return RawDensity(
            structure=self._read_structure(),
            charge=self._h5f["charge/charge"],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def dielectric_function(self):
        """Read the dielectric functions.

        Returns
        -------
        DataDict[str, RawDielectricFunction]
            The key specifies, which dielectric function is contained. The value
            represents the energy-resolved dielectric tensor.
        """
        return self._make_data_dict(self._read_dielectric_function())

    def _read_dielectric_function(self):
        self._raise_error_if_closed()
        group = "results/linear_response"
        suffix = "_dielectric_function"
        if group not in self._h5f:
            return None
        return RawDielectricFunction(
            energies=self._h5f[f"{group}/energies{suffix}"],
            density_density=self._safe_get_key(f"{group}/density_density{suffix}"),
            current_current=self._safe_get_key(f"{group}/current_current{suffix}"),
            ion=self._safe_get_key(f"{group}/ion{suffix}"),
        )

    @property
    def force(self):
        """Read the forces for all ionic steps.

        Returns
        -------
        DataDict[str, RawForce]
            The key specifies how the forces are obtained. The value represents the
            information about structure and forces.
        """
        return self._make_data_dict(default=self._read_force())

    def _read_force(self):
        self._raise_error_if_closed()
        return RawForce(
            structure=self._read_structure(),
            forces=self._h5f["intermediate/ion_dynamics/forces"],
        )

    @property
    def stress(self):
        """Read the stress for all ionic steps.

        Returns
        -------
        DataDict[str, RawStress]
            The key specifies how the stress is obtained. The value represents the
            information about structure and stress.
        """
        return self._make_data_dict(default=self._read_stress())

    def _read_stress(self):
        self._raise_error_if_closed()
        return RawStress(
            structure=self._read_structure(),
            stress=self._h5f["intermediate/ion_dynamics/stress"],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def force_constant(self):
        """Read the force constants from a linear response calculation.

        Returns
        -------
        DataDict[str, RawForceConstant]
            The key specifies how the force constants are obtained. The value represents
            information about the structure and the force constants matrix.
        """
        return self._make_data_dict(default=self._read_force_constant())

    def _read_force_constant(self):
        self._raise_error_if_closed()
        return RawForceConstant(
            structure=self._read_structure(),
            force_constants=self._h5f["results/linear_response/force_constants"],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def dielectric_tensor(self):
        """Read the dielectric tensor from a linear response calculation.

        Returns
        -------
        DataDict[str, RawDielectricTensor]
            The key specifies which dielectric tensor is contained. The value describes
            the contributions to the dielectric tensor and the generating methodology.
        """
        return self._make_data_dict(self._read_dielectric_tensor())

    def _read_dielectric_tensor(self):
        self._raise_error_if_closed()
        group = "results/linear_response"
        key_independent_particle = f"{group}/independent_particle_dielectric_tensor"
        if key_independent_particle in self._h5f:
            independent_particle = self._h5f[key_independent_particle]
        else:
            independent_particle = None
        return RawDielectricTensor(
            electron=self._h5f[f"{group}/electron_dielectric_tensor"],
            ion=self._h5f[f"{group}/ion_dielectric_tensor"],
            independent_particle=independent_particle,
            method=self._h5f[f"{group}/method_dielectric_tensor"][()],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def born_effective_charge(self):
        """Read the Born effective charges from a linear response calculation.

        Returns
        -------
        DataDict[str, RawBornEffectiveCharges]
            The key identifies the nature of the Born effective charges, the value
            provides the raw data and structural information.
        """
        return self._make_data_dict(self._read_born_effective_charge())

    def _read_born_effective_charge(self):
        self._raise_error_if_closed()
        return RawBornEffectiveCharge(
            structure=self._read_structure(),
            charge_tensors=self._h5f["results/linear_response/born_charges"],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def internal_strain(self):
        """Read the internal strain from a linear response calculation.

        Returns
        -------
        DataDict[str, RawInternalStrain]
            The key identifies the source of the internal strain, the value provides
            the raw data and structural information.
        """
        return self._make_data_dict(self._read_internal_strain())

    def _read_internal_strain(self):
        self._raise_error_if_closed()
        return RawInternalStrain(
            structure=self._read_structure(),
            internal_strain=self._h5f["results/linear_response/internal_strain"],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def elastic_modulus(self):
        """Read the elastic modulus from a linear response calculation.

        Returns
        -------
        DataDict[str, RawElasticModulus]
            The key identifies the source of the elastic modulus, the value provides
            the raw data for relaxed ion and clamped ion elastic modulus.
        """
        return self._make_data_dict(self._read_elastic_modulus())

    def _read_elastic_modulus(self):
        self._raise_error_if_closed()
        group = "results/linear_response"
        return RawElasticModulus(
            clamped_ion=self._h5f[f"{group}/clamped_ion_elastic_modulus"],
            relaxed_ion=self._h5f[f"{group}/relaxed_ion_elastic_modulus"],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def piezoelectric_tensor(self):
        """Read the piezoelectric tensor from a linear response calculation.

        Returns
        -------
        DataDict[str, RawPiezoelectricTensor]
            The key identifies the source of the piezoelectric tensor, the value
            provides the raw data for electronic and ionic contribution to the
            piezoelectric tensor.
        """
        return self._make_data_dict(self._read_piezoelectric_tensor())

    def _read_piezoelectric_tensor(self):
        self._raise_error_if_closed()
        group = "results/linear_response"
        return RawPiezoelectricTensor(
            electron=self._h5f[f"{group}/electron_piezoelectric_tensor"],
            ion=self._h5f[f"{group}/ion_piezoelectric_tensor"],
        )

    @property
    @_version.require(RawVersion(6, 3))
    def polarization(self):
        """Read the electronic and ionic dipole moments from a linear response
        calculation.

        Returns
        -------
        DataDict[str, RawPolarization]
            The key identifies the source of the polarization, the value provides
            the raw data for electronic and ionic contribution to the dipole
            moment.
        """
        return self._make_data_dict(self._read_polarization())

    def _read_polarization(self):
        self._raise_error_if_closed()
        group = "results/linear_response"
        return RawPolarization(
            electron=self._h5f[f"{group}/electron_dipole_moment"],
            ion=self._h5f[f"{group}/ion_dipole_moment"],
        )

    def close(self):
        "Close the associated HDF5 file (automatically if used as context manager)."
        self._h5f.close()
        self.closed = True

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _make_data_dict(self, default, **other):
        return DataDict({"default": default, **other}, self.version)

    def _raise_error_if_closed(self):
        if self.closed:
            raise exception.FileAccessError("I/O operation on closed file.")

    def _safe_get_key(self, key):
        if key in self._h5f:
            return self._h5f[key]
        else:
            return None
