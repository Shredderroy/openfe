# This code is part of OpenFE and is licensed under the MIT license.
# For details, see https://github.com/OpenFreeEnergy/openfe
"""
Reusable utility methods to validate input settings to OpenMM-based alchemical
Protocols.
"""
from openff.units import unit, Quantity
from typing import Optional
from .omm_settings import (
    IntegratorSettings,
    MultiStateSimulationSettings,
)
from openfe.protocols.openmm_utils.omm_settings import OpenMMSolvationSettings


def validate_openmm_solvation_settings(
    settings: OpenMMSolvationSettings
) -> None:
    """
    Checks that the OpenMMSolvation settings are correct.

    Raises
    ------
    ValueError
      If more than one of ``solvent_padding``, ``number_of_solvent_molecules``,
      ``box_vectors``, or ``box_size`` are defined.
      If ``box_shape`` is defined alongside either ``box_vectors``,
      or ``box_size``.
    """
    unique_attributes = (
        settings.solvent_padding, settings.number_of_solvent_molecules,
        settings.box_vectors, settings.box_size,
    )
    if len([x for x in unique_attributes if x is not None]) > 1:
        errmsg = ("Only one of solvent_padding, number_of_solvent_molecules, "
                  "box_vectors, and box_size can be defined in the solvation "
                  "settings.")
        raise ValueError(errmsg)

    if settings.box_shape is not None:
        if settings.box_size is not None or settings.box_vectors is not None:
            errmsg = ("box_shape cannot be defined alongside either box_size "
                      "or box_vectors in the solvation settings.")
            raise ValueError(errmsg)


def validate_timestep(hmass: float, timestep: Quantity):
    """
    Check that the input timestep is suitable for the given hydrogen
    mass.

    Parameters
    ----------
    hmass : float
      The target hydrogen mass (assumed units of amu).
    timestep : openff.units.Quantity
      The integration time step.


    Raises
    ------
    ValueError
      If the hydrogen mass is less than 3 amu and the timestep is
      greater than 2 fs.
    """
    if hmass < 3.0:
        if timestep > 2.0 * unit.femtoseconds:
            errmsg = f"timestep {timestep} too large for hydrogen mass {hmass}"
            raise ValueError(errmsg)


def get_simsteps(sim_length: Quantity,
                 timestep: Quantity, mc_steps: int) -> int:
    """
    Gets and validates the number of simulation steps.

    Parameters
    ----------
    sim_length : openff.units.Quantity
      Simulation length.
    timestep : openff.units.Quantity
      Integration timestep.
    mc_steps : int
      Number of integration timesteps between MCMC moves.

    Returns
    -------
    sim_steps : int
      The number of simulation timesteps.
    """

    sim_time = round(sim_length.to('attosecond').m)  # type: ignore
    ts = round(timestep.to('attosecond').m)  # type: ignore

    sim_steps, mod = divmod(sim_time, ts)
    if mod != 0:
        raise ValueError("Simulation time not divisible by timestep")

    if (sim_steps % mc_steps) != 0:
        errmsg =  (f"Simulation time {sim_time/1000000} ps should contain a "
                   "number of steps divisible by the number of integrator "
                   f"timesteps between MC moves {mc_steps}")
        raise ValueError(errmsg)

    return sim_steps


def divmod_time(
    time: Quantity,
    time_per_iteration: Quantity,
) -> tuple[int, int]:
    """
    Convert a set amount of time to a number of iterations.

    Parameters
    ---------
    time: openff.units.Quantity
      The time to convert.
    time_per_iteration : openff.units.Quantity
      The amount of time which each iteration takes.

    Returns
    -------
    iterations : int
      The number of iterations covered by the input time.
    remainder : int
      The remainder of the input time and time_per_iteration division.
    """
    time_ats = round(time.to(unit.attosecond).m)  # type: ignore
    tpi_ats = round(time_per_iteration.to(unit.attosecond).m)  # type: ignore

    iterations, remainder = divmod(time_ats, tpi_ats)

    return iterations, remainder


def divmod_time_and_check(numerator: Quantity, denominator: Quantity,
                          numerator_name: str, denominator_name: str) -> int:
    """Perform a division of time, failing if there is a remainder

    For example numerator 20.0 ps and denominator 4.0 fs gives 5000

    Parameters
    ----------
    numerator, denominator : openff.units.Quantity
      the division to perform
    numerator_name, denominator_name : str
      used for the error generated if there is any remainder

    Returns
    -------
    iterations : int
      the result of the division

    Raises
    ------
    ValueError
      if the division results in any remainder, will include a formatted error
      message
    """
    its, rem = divmod_time(numerator, denominator)

    if rem:
        errmsg = (f"The {numerator_name} ({numerator}) "
                  "does not evenly divide by the "
                  f"{denominator_name} ({denominator})")
        raise ValueError(errmsg)

    return its


def convert_checkpoint_interval_to_iterations(
    checkpoint_interval: Quantity,
    time_per_iteration: Quantity,
) -> int:
    """
    Get the number of iterations per checkpoint interval.

    This is necessary as our input settings define checkpoints intervals in
    units of time, but OpenMMTools' MultiStateReporter requires them defined
    in the number of MC intervals.

    Parameters
    ----------
    checkpoint_interval : openff.units.Quantity
      The amount of time per checkpoints written.
    time_per_iteration : openff.units.Quantity
      The amount of time each MC iteration takes.

    Returns
    -------
    iterations : int
      The number of iterations per checkpoint.
    """
    iterations, rem = divmod_time(checkpoint_interval, time_per_iteration)

    if rem:
        errmsg = (f"The amount of time per checkpoint {checkpoint_interval} "
                  "does not evenly divide by the amount of time per "
                  f"state MCMC move attempt {time_per_iteration}")
        raise ValueError(errmsg)

    return iterations


def convert_steps_per_iteration(
    simulation_settings: MultiStateSimulationSettings,
    integrator_settings: IntegratorSettings,
) -> int:
    """Convert time per iteration to steps

    Parameters
    ----------
    simulation_settings: MultiStateSimulationSettings
    integrator_settings: IntegratorSettings

    Returns
    -------
    steps_per_iteration : int
      suitable for input to Integrator
    """
    return divmod_time_and_check(
        simulation_settings.time_per_iteration,
        integrator_settings.timestep,
        "time_per_iteration",
        "timestep",
    )


def convert_real_time_analysis_iterations(
    simulation_settings: MultiStateSimulationSettings,
) -> tuple[Optional[int], Optional[int]]:
    """Convert time units in Settings to various other units

    Interally openmmtools uses various quantities with units of time,
    steps, and iterations.

    Our Settings objects instead have things defined in time (fs or ps).

    This function generates suitable inputs for the openmmtools objects

    Parameters
    ----------
    simulation_settings: MultiStateSimulationSettings

    Returns
    -------
    real_time_analysis_iterations : Optional[int]
      suitable for input to online_analysis_interval
    real_time_analysis_minimum_iterations : Optional[int]
      suitable for input to real_time_analysis_minimum_iterations
    """
    if simulation_settings.real_time_analysis_interval is None:
        # option to turn off real time analysis
        return None, None

    rta_its = divmod_time_and_check(
        simulation_settings.real_time_analysis_interval,
        simulation_settings.time_per_iteration,
        "real_time_analysis_interval",
        "time_per_iteration",
    )
    rta_min_its = divmod_time_and_check(
        simulation_settings.real_time_analysis_minimum_time,
        simulation_settings.time_per_iteration,
        "real_time_analysis_minimum_time",
        "time_per_iteration",
    )

    return rta_its, rta_min_its


def convert_target_error_from_kcal_per_mole_to_kT(
    temperature,
    target_error,
) -> float:
    """Convert kcal/mol target error to kT units

    If target_error is 0.0, returns 0.0

    Parameters
    ----------
    temperature : openff.units.Quantity
      temperature in K
    target_error : openff.units.Quantity
      error in kcal/mol

    Returns
    -------
    early_termination_target_error : float
      in units of kT, suitable for input as "online_analysis_target_error" in a
      Sampler
    """
    if target_error:
        kB = 0.001987204 * unit.kilocalorie_per_mole / unit.kelvin
        kT = temperature * kB
        early_termination_target_error = target_error / kT
    else:
        return 0.0

    return early_termination_target_error.m
