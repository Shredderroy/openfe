# This code is part of OpenFE and is licensed under the MIT license.
# For details, see https://github.com/OpenFreeEnergy/openfe
import numpy as np
from numpy.testing import assert_allclose
from gufe.protocols import execute_DAG
import pytest
from openff.units import unit
import pathlib

import openfe
from openfe.protocols import openmm_rfe


@pytest.mark.slow
@pytest.mark.flaky(reruns=3)  # pytest-rerunfailures; we can get bad minimization
@pytest.mark.parametrize('platform', ['CPU', 'CUDA'])
def test_openmm_run_engine(
    benzene_vacuum_system,
    platform,
    get_available_openmm_platforms,
    benzene_modifications,
    tmpdir
):
    if platform not in get_available_openmm_platforms:
        pytest.skip(f"OpenMM Platform: {platform} not available")
    # this test actually runs MD
    # these settings are a small self to self sim, that has enough eq that
    # it doesn't occasionally crash
    s = openfe.protocols.openmm_rfe.RelativeHybridTopologyProtocol.default_settings()
    s.simulation_settings.equilibration_length = 0.1 * unit.picosecond
    s.simulation_settings.production_length = 0.1 * unit.picosecond
    s.simulation_settings.time_per_iteration = 20 * unit.femtosecond
    s.forcefield_settings.nonbonded_method = 'nocutoff'
    s.protocol_repeats = 1
    s.engine_settings.compute_platform = platform
    s.output_settings.checkpoint_interval = 20 * unit.femtosecond
    s.output_settings.positions_write_frequency = 20 * unit.femtosecond

    p = openmm_rfe.RelativeHybridTopologyProtocol(s)

    b = benzene_vacuum_system['ligand']

    # make a copy with a different name
    rdmol = benzene_modifications['benzene'].to_rdkit()
    b_alt = openfe.SmallMoleculeComponent.from_rdkit(rdmol, name='alt')
    benzene_vacuum_alt_system = openfe.ChemicalSystem({
        'ligand': b_alt
    })

    m = openfe.LigandAtomMapping(
        componentA=b,
        componentB=b_alt,
        componentA_to_componentB={i: i for i in range(12)}
    )
    dag = p.create(
        stateA=benzene_vacuum_system,
        stateB=benzene_vacuum_alt_system,
        mapping=[m]
    )

    cwd = pathlib.Path(str(tmpdir))
    r = execute_DAG(dag, shared_basedir=cwd, scratch_basedir=cwd,
                    keep_shared=True)

    assert r.ok()
    for pur in r.protocol_unit_results:
        unit_shared = tmpdir / f"shared_{pur.source_key}_attempt_0"
        assert unit_shared.exists()
        assert pathlib.Path(unit_shared).is_dir()

        # Check the checkpoint file exists
        checkpoint = pur.outputs['last_checkpoint']
        assert checkpoint == "checkpoint.chk"
        assert (unit_shared / checkpoint).exists()

        # Check the nc simulation file exists
        # TODO: assert the number of frames
        nc = pur.outputs['nc']
        assert nc == unit_shared / "simulation.nc"
        assert nc.exists()

        # Check structural analysis contents
        structural_analysis_file = unit_shared / "structural_analysis.npz"
        assert (structural_analysis_file).exists()
        assert pur.outputs['structural_analysis'] == structural_analysis_file

        structural_data = np.load(pur.outputs['structural_analysis'])
        structural_keys = [
            'protein_RMSD', 'ligand_RMSD', 'ligand_COM_drift',
            'protein_2D_RMSD', 'time_ps'
        ]
        for key in structural_keys:
            assert key in structural_data.keys()

        # 6 frames being written to file
        assert_allclose(structural_data['time_ps'], [0.0, 0.02, 0.04, 0.06, 0.08, 0.1])
        assert structural_data['ligand_RMSD'].shape == (11, 6)
        assert structural_data['ligand_COM_drift'].shape == (11, 6)
        # No protein so should be empty
        assert structural_data['protein_RMSD'].size == 0
        assert structural_data['protein_2D_RMSD'].size == 0

    # Test results methods that need files present
    results = p.gather([r])
    states = results.get_replica_states()
    assert len(states) == 1
    assert states[0].shape[1] == 11


@pytest.mark.integration  # takes ~7 minutes to run
@pytest.mark.flaky(reruns=3)
def test_run_eg5_sim(eg5_protein, eg5_ligands, eg5_cofactor, tmpdir):
    # this runs a very short eg5 complex leg
    # different to previous test:
    # - has a cofactor
    # - has an alchemical swap present
    # - runs in solvated protein
    # if this passes 99.9% chance of a good time
    s = openfe.protocols.openmm_rfe.RelativeHybridTopologyProtocol.default_settings()
    s.simulation_settings.equilibration_length = 0.1 * unit.picosecond
    s.simulation_settings.production_length = 0.1 * unit.picosecond
    s.simulation_settings.time_per_iteration = 20 * unit.femtosecond
    s.protocol_repeats = 1
    s.output_settings.checkpoint_interval = 20 * unit.femtosecond

    p = openmm_rfe.RelativeHybridTopologyProtocol(s)

    base_sys = {
        'protein': eg5_protein,
        'cofactor': eg5_cofactor,
        'solvent': openfe.SolventComponent(),
    }
    # this is just a simple (unmapped) *-H -> *-F switch
    l1, l2 = eg5_ligands[0], eg5_ligands[1]
    m = openfe.LigandAtomMapping(
        componentA=l1, componentB=l2,
        # a bit lucky, first 51 atoms map to each other, H->F swap is at 52
        componentA_to_componentB={i: i for i in range(51)}
    )

    sys1 = openfe.ChemicalSystem(components={**base_sys, 'ligand': l1})
    sys2 = openfe.ChemicalSystem(components={**base_sys, 'ligand': l2})

    dag = p.create(stateA=sys1, stateB=sys2,
                   mapping=[m])

    cwd = pathlib.Path(str(tmpdir))
    r = execute_DAG(dag, shared_basedir=cwd, scratch_basedir=cwd,
                    keep_shared=True)

    assert r.ok()


@pytest.mark.integration
@pytest.mark.flaky(reruns=3)
def test_run_dodecahedron_sim(
    benzene_system, toluene_system, benzene_to_toluene_mapping, tmpdir
):
    """
    Test that we can run a ligand in solvent RFE with a non-cubic box
    """
    settings = openmm_rfe.RelativeHybridTopologyProtocol.default_settings()
    settings.solvation_settings.solvent_padding = 1.5 * unit.nanometer
    settings.solvation_settings.box_shape = 'dodecahedron'
    settings.protocol_repeats = 1
    settings.simulation_settings.equilibration_length = 0.1 * unit.picosecond
    settings.simulation_settings.production_length = 0.1 * unit.picosecond
    settings.simulation_settings.time_per_iteration = 20 * unit.femtosecond
    settings.output_settings.checkpoint_interval = 20 * unit.femtosecond
    protocol = openmm_rfe.RelativeHybridTopologyProtocol(settings=settings)

    dag = protocol.create(
        stateA=benzene_system,
        stateB=toluene_system,
        mapping=benzene_to_toluene_mapping,
    )

    cwd = pathlib.Path(str(tmpdir))

    r = execute_DAG(
        dag,
        shared_basedir=cwd,
        scratch_basedir=cwd,
        keep_shared=True
    )

    assert r.ok()
