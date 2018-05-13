# -*- coding: utf-8 -*-
from pcraster._pcraster import *
from pcraster.framework import *
from copy import deepcopy

# import os
# import time
# print(os.getcwd())

DEBUG = False


def getBiomassCover(model, frac_soil_cover):
    # biomass cover conversion (SWAT adaptation)
    # SWAT requires CV (Kg/Ha) to compute soil cover index, here we assume frac_soil_cover as the index,
    # and use it to inversely obtain biomass_cover (CV)
    # eq. 1:1.2.16 (p. 37, SWAT)
    biomass_cover = ifthenelse(frac_soil_cover > scalar(0), ln(frac_soil_cover) / (-5 * float(10) ** (-5)),
                               scalar(0))
    # eq. 1:1.3.11, (p. 44, SWAT)
    bcv = biomass_cover / (biomass_cover + exp(7.563 - 1.297 * 10 ** (-4) * biomass_cover))
    # model.bcvTss.sample(bcv)  # bcv should range 0 (bare soil) to 1 (complete cover)

    # frac_soil_cover is obtained via:
    # frac_soil_cover = 1 - exp(-mu * LAI) <- function of dev. stage and max LAI!
    # Alternatively, could be obtained as:
    # frac_soil_cover = ((Kcb - Kcmin)/(Kcmax - Kcmin))^(1+0.5*mean_height)  # In: Allen1998
    return bcv


# Conversions
def convertJulian(year, month, day):
    # date_factor_crop = -1 or 1
    date_factor_crop = ifthenelse(100 * year + month - 190002.5 < scalar(0), scalar(-1), scalar(1))

    julian_day = 367 * year - rounddown(7 * (year + rounddown((month + 9) / float(12))) / 4) + rounddown(
        (275 * month) / float(9)) + day + 1721013.5 - 0.5 * date_factor_crop
    return julian_day


# Computations
def runoff_SCS(model, rain,
               theta_sat_z0z1, theta_fcap_z0z1, theta_wp, CN2, crop_type,
               jd_sim, jd_dev, jd_mid, jd_end,
               len_dev_stage  #, soil_group
               ):
    """
    Returns run-off amount in mm
    Retention parameters are calculated based on the first two model layers (z0 and z1)
        Therefore, when calculating percolation from z0 to z1, water content
        should be distributed between these two layers based on an appropriate rule.
        Options:
        i) distribute water content proportionally to layer's depth
        ii) saturate z0 first, allocate remaining to z1 (current option chosen)
    """
    # Curve Number guidelines:
    # https://www.nrcs.usda.gov/Internet/FSE_DOCUMENTS/stelprdb1044171.pdf
    # Will assume HSG Group C (final infiltration rate 1.3-3.8 mm per hour)

    CN2_table = {"Corn": {"A": 72, "B": 81, "C": 88, "D": 91},  # poor HC
                 "Wheat": {"A": 72, "B": 81, "C": 88, "D": 91},  # poor HC
                 "Beet": {"A": 72, "B": 81, "C": 88, "D": 91},  # poor HC
                 "Greenery": {"A": 35, "B": 56, "C": 70, "D": 77},  # Brush, fair HC, # Table 2-2c
                 "Dirt Road": {"A": 72, "B": 82, "C": 87, "D": 89},  # Table 2-2a
                 "Grass Road": {"A": 59, "B": 74, "C": 82, "D": 86},  # Farmsteads, # Table 2-2c
                 "Paved Road": {"A": 98, "B": 98, "C": 98, "D": 98},  # Table 2-2a
                 "Ditch": {"A": 98, "B": 98, "C": 98, "D": 98},  # Paved -> should add to vol.
                 "Fallow": {"A": 30, "B": 58, "C": 71, "D": 78},  # Assumed Meadow, Table 2-2c
                 "Hedge": {"A": 35, "B": 56, "C": 70, "D": 77},  # Brush, fair HC, # Table 2-2c
                 "Orchard": {"A": 43, "B": 65, "C": 76, "D": 82},  # Woods-grass, fair HC, # Table 2-2c
                 "Bare Soil": {"A": 77, "B": 86, "C": 91, "D": 94}  # Fallow on Table, 2-2b, but Bare Soil treatment
                 }

    # SFCD0=thetaFCD0*self.depth0 # conversion of percentage moisture to mm of water
    SFC1 = theta_fcap_z0z1 * (model.layer_depth[1] + model.layer_depth[0])  # conversion of percentage moisture to mm of water

    # SWPD0=theta_wp*self.depth0
    SWP = theta_wp * (model.layer_depth[1] + model.layer_depth[0])

    # TODO: Check if improvements can be done with adapting below to stage...
    # adjusting CN values based on crop
    # CN2 = ifthenelse(crop_type > scalar(5), CN2,  # x > 5, not a crop in 2016
    #                  ifthenelse(crop_type == scalar(0), CN2,  # Not a crop
    #                             ifthenelse(jd_sim < jd_dev,  # Before planting (i.e. fallow, bare soil)
    #                                        scalar(CN2_table["Bare Soil"][soil_group]),
    #                                        ifthenelse(jd_sim <= jd_mid,  # Growth stage
    #                                                   (CN2 + (scalar(CN2_table["Bare Soil"][soil_group]) - CN2) *
    #                                                    ((jd_mid - jd_sim) / len_dev_stage)),
    #                                                   ifthenelse(jd_sim <= jd_end,
    #                                                              CN2, scalar(CN2_table["Bare Soil"][soil_group])
    #                                                              )))))

    # calculation of CN1 and CN2 based on CN2 values
    CN3 = CN2 * exp(0.00673 * (100 - CN2))
    CN2s = (CN3 - CN2) / float(3) * (1 - 2 * exp(-13.86 * model.slope)) + CN2
    CN1 = CN2s - (float(20) * (100 - CN2s)) / (100 - CN2s + exp(2.533 - 0.0636 * (100 - CN2s)))
    CN3 = CN2s * exp(0.00673 * (100 - CN2s))

    # calculation of retention parameter for antecedent moisture condition III
    S3 = 254 * (float(100) / CN3 - 1)

    # calculation of maximum retention parameter of SCS
    Smax = 254 * (float(100) / CN1 - 1)

    # SSD0=thetaSD0*self.depth0
    SS1 = theta_sat_z0z1 * (model.layer_depth[1] + model.layer_depth[0])

    # Calculation of w1 and w2 parameters for obtaining CN values related to moisture content
    w2 = (ln(SFC1 / (1 - (S3 / Smax)) - SFC1) - ln(SS1 / (1 - (2.54 / Smax)) - SS1)) / (SS1 - SFC1)
    w1 = ln(SFC1 / (1 - (S3 / Smax)) - SFC1) + w2 * SFC1
    # SW=self.theta_z1*(D1+10)-SWP;

    # Moisture content [-] of first two depths -> avoids excessive runoff
    theta_d0d1 = (model.layer_depth[0] * model.theta_z0 + model.layer_depth[1] * model.theta_z1) / (model.layer_depth[0] + model.layer_depth[1])
    # try:
    #     model.thetaD0D1tss.sample(theta_d0d1)
    # except AttributeError, e:
    #     print(e)

    # Soil Water content in mm (soil column of first two depths)
    # -> avoids ecessive runoff by considering not only the first very shallow layer saturation capacity
    SW = max((theta_d0d1 - theta_wp) * (model.layer_depth[0] + model.layer_depth[1]), scalar(0))
    # self.SWtss.self(SW)

    # calculation of retention parameter
    S = Smax * (1 - (SW / (SW + exp(w1 - w2 * SW))))

    # calculation of runoff [mm] for every cell in layer z0 for each time step
    runoff = ifthenelse(rain > 0.2 * S, ((rain - 0.2 * S) ** 2) / (rain + 0.8 * S), scalar(0))
    return runoff


def getLayerMoisture(model, layer,
                     precip, theta_wp, CN2, crop_type,  #soil_group,
                     jd_sim, jd_dev, jd_mid, jd_end,
                     len_dev_stage,
                     root_depth, pot_evapor, pot_transpir, depletable_water,
                     # Layer-specific information
                     k_sat,
                     root_depth_layer,
                     theta_fcap, theta_sat,  # field and saturation capacity (crop.tbl)
                     percolate=0, satex=0,  # Need to add these values for layers > 0 (layer 1 only for now)
                     isPermeable=True,
                     ADLF=False, c_adr=0.25  # Artificial drainage lateral flow, and correction factor (adr)
                     ):
    """
    :type model: instance of "model"
    :param layer: layer integer (i.e., 0, 1, or 2)
    :param precip: precipitation (mm)
    :param CN2: Initial curve number (crop table or adjusted)
    :param crop_type: Need it only for layer z = 0, where runoff_SCS() is called
    :param theta_wp: wilting point for respective layer
    :param theta_fcap: field capacity for respective layer

    :param percolate: amount certainly lost to sub-layer
    :param satex: considers additional percolation to layer z = 1
                    due to small thickness of mixing layer (i.e., in z = 0)
    """
    # DEBUG
    water_balance_layer = None
    ETP = False

    layer_params = {'depth': 'model.z' + str(layer),
                    'theta': 'model.theta_z' + str(layer),
                    'temp_lagged': 'model.temp_z' + str(layer) + '_fin',
                    # 'c': 'model.c_lf' + str(layer),
                    # 'gamma': 'model.gamma' + str(layer),
                    # 's': 'model.s' + str(layer),
                    'theta_layer': 'model.theta_z' + str(layer),
                    'theta_ini': 'model.theta_z' + str(layer)}

    # depth = eval(layer_params['depth'])
    depth = model.layer_depth[layer]
    c = model.c_lf[layer]
    gamma = model.gamma[layer]
    s = model.s[layer]
    theta_layer = eval(layer_params['theta_layer'])
    theta_ini = eval(layer_params['theta_ini'])

    tau = min(0.0866 * exp(gamma * log10(s * k_sat)), 1)  # dimensionless drainage param.
    zero_map = depth - depth
    cell_drainge_outflow = deepcopy(zero_map)  # Activated only on relevant layer(s)
    # Run-off, infiltration, artificial drainage & percolation
    ##########################
    if layer == 0:
        roff_z0 = runoff_SCS(model, precip,
                             theta_sat, theta_fcap, theta_wp, CN2, crop_type,
                             jd_sim, jd_dev, jd_mid, jd_end,
                             len_dev_stage #, #soil_group
                             )

        # Infiltration [mm] based on
        # retention parameter "S" with depth = 150mm (i.e. z0 + z1)
        infil = precip - roff_z0
        # A) Check for excess (i.e. above saturation):
        theta_temp_check_z0 = model.theta_z0 + (infil / model.layer_depth[0])
        # theta_sat_z0z1 (saturation capacity [-]) is equal for z0 and z1
        satex_z0 = ifthenelse(theta_temp_check_z0 > theta_sat,
                              theta_temp_check_z0 - theta_sat,
                              scalar(0))
        theta_temp_check_z0 = ifthenelse(theta_temp_check_z0 > theta_sat,
                                         theta_sat, theta_temp_check_z0)
        # try:
        #     model.z0Check_satex.sample(satex_z0 * model.layer_depth[0])
        # except AttributeError, e:
        #     print(e)

        # Deep percolation (Raes, 2002, in Sheikh2009)
        deep_percolation_z0 = ifthenelse(theta_temp_check_z0 > theta_fcap,
                                         tau * depth * (theta_sat - theta_fcap) *
                                         ((exp(theta_layer - theta_fcap)) - 1) /
                                         ((exp(theta_sat - theta_fcap)) - 1),
                                         scalar(0))  # [mm]

        # A2) Allocate mass to z1 and check for excess
        # This is needed if SCS method considers z0 and z1 simultaneously.
        theta_temp_check_z1 = model.theta_z1 + satex_z0 + deep_percolation_z0 / model.layer_depth[0]

        satex_z1 = ifthenelse(theta_temp_check_z1 > theta_sat,
                              theta_temp_check_z1 - theta_sat,
                              scalar(0))
        # Infiltration adjusted, correct runoff
        infil = precip - (roff_z0 + satex_z1)
        roff_z0 += satex_z1
        # runoff_m3 = roff_z0 * cellarea() / 1000  # runoff in m3

        theta_temp_z0 = model.theta_z0 + (infil / model.layer_depth[0])
        satex = ifthenelse(theta_temp_z0 > theta_sat,
                           theta_temp_z0 - theta_sat,
                           scalar(0))
        theta_layer = ifthenelse(theta_temp_z0 > theta_sat,
                                      theta_sat, theta_temp_z0)

        # Deep percolation
        ###################
        # In: Sheikh2009
        # Based on:
        # Raes, D., 2002.
        # BUDGET: a Soil Water and Salt Balance Model.
        # Reference manual. Version 5.0. Catholic University of Leuven, Belgium.
        deep_percolation = ifthenelse(theta_layer > theta_fcap,
                                      tau * depth * (theta_sat - theta_fcap) *
                                      ((exp(theta_layer - theta_fcap)) - 1) /
                                      ((exp(theta_sat - theta_fcap)) - 1),
                                      scalar(0))  # [mm]

        theta_layer -= deep_percolation / depth
        theta_after_percolate = theta_layer
        theta_ini_mm = model.theta_z0 * depth

    else:  # Subsurface layers
        roff_z0 = zero_map
        # Percolation from above
        infil = percolate
        if layer == 1:  # Add excess saturation from top 1cm
            infil += satex * model.layer_depth[0]
        # Add infiltration from above
        theta_layer += infil / depth
        # Check for possible error (due to excess infiltration)
        satex_z = ifthenelse(theta_layer > theta_sat,
                             theta_layer - theta_sat, scalar(0))

        if mapmaximum(satex_z) > 0:
            model.report(satex_z * depth * cellarea()/1000, 'aSatXz' + str(layer))  # m3, should always be zero

        # Lateral Flow (artificial drainage)
        ###############
        if ADLF:  # is there artificial drainage on this layer?
            # Cell outflow
            cell_drainge_outflow = max(c_adr * (depth * theta_layer - depth * theta_fcap), scalar(0))  # [mm]
            theta_layer -= cell_drainge_outflow / depth
        else:
            cell_drainge_outflow = scalar(0)

        # Percolation to below layer
        if isPermeable:  # Is this layer permeable?
            potential = tau * depth * (theta_sat - theta_fcap) * \
                        ((exp(theta_layer - theta_fcap)) - 1) / ((exp(theta_sat - theta_fcap)) - 1)
            deep_percolation = ifthenelse(theta_layer > theta_fcap, potential, scalar(0))  # [mm]
            # min(potential, depth*(theta_layer-theta_fcap))
        else:
            deep_percolation = scalar(0)

        # Update moisture & balance layer
        theta_test = deepcopy(theta_layer)
        theta_test -= deep_percolation / depth

        # Check:
        if mapminimum(theta_test) < 0:
            theta_layer = ifthenelse(theta_test < 0, theta_layer, theta_test)
            print("Theta mapminimum < 0")
            print("time step: ", model.currentTimeStep())
            print("Tau: ", tau)
            model.report(deep_percolation, "err_DP")
            model.report(theta_layer, "err_z2")
            model.report((deep_percolation / depth), "err_SW")
        else:
            theta_layer -= deep_percolation / depth

        theta_after_percolate = theta_layer

    # Lateral Flow
    ###############
    # In: Sheikh2009
    # Based on:
    # Manfreda, S., Fiorentino, M., Iacobellis, V., 2005.
    # DREAM: a distributed model for runoff, evapotranspiration, and
    # antecedent soil moisture simulation. Adv. Geosci. 2, 31–39.
    ################
    # PCRaster:
    # net_flux = accuflux(ldd, material)
    # accuflux calculates for each cell the accumulated amount of material that flows out of the cell
    # material = (in this case) effective moisture above field capacity
    # model.wetness = W index = (4m2*number of upstream cells)/slope
    test_latflow = False
    if test_latflow:
        cell_moisture_outflow = model.zero_map
        upstream_cell_inflow = model.zero_map
        lateral_flow_layer = upstream_cell_inflow - cell_moisture_outflow
    else:
        # Cell outflow
        cell_moisture_outflow = max(c * (depth * theta_layer - depth * theta_fcap), scalar(0))  # [mm]

        # Note denominator's accuflux 2nd parameter below by Samuel is = Wetness1
        # State_1 = cell_moisture_outflow
        # model.wetness1 = ifthenelse(State_1> 0,Wetness,0)
        # Cell inflow
        upstream_cell_inflow = (model.wetness * accuflux(model.ldd_subs, cell_moisture_outflow)) / accuflux(
            model.ldd_subs,
            model.wetness)
        # Cell inflow - cell outflow
        # TODO: Doubt:
        # Verify that that the inflow component is appropriate against Sheikh2009's formalism.
        lateral_flow_layer = upstream_cell_inflow - cell_moisture_outflow  # [mm]

    # Water Mass Balance & Moisture Update #######
    theta_layer += lateral_flow_layer / depth
    overflow = ifthenelse(theta_layer > theta_sat, theta_layer - theta_sat, scalar(0))
    theta_layer -= overflow
    overflow_height = overflow * depth  # mm

    # Evapotranspiration
    #####################
    # In: Sheikh2009
    # Based on:
    # Allen1998: Simplified version of the Penman–Monteith (FAO56) approach:
    # Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998.
    # Crop evapotranspiration: guidelines for computing cropwater requirements.
    # In: Irrigation and Drainage. Paper 56. FAO, Rome.
    ################

    if ETP:
        pot_transpir_layer = ifthenelse(root_depth > scalar(0),
                                        2 * (1 - (root_depth_layer / float(2)) / root_depth) *
                                        (root_depth_layer / root_depth) * pot_transpir,
                                        scalar(0))  # proportion of transpiration in surface layer

        # Transpiration
        # Critical moisture content defines
        # transition btw. unstressed and stressed transpiration rate
        theta_critical_layer = theta_wp + (1 - depletable_water) * (theta_fcap - theta_wp)

        # Transpiration reduction parameter (0 - 1)
        ks_layer = max(0, min(1, (theta_layer - theta_wp) / (theta_critical_layer - theta_wp)))

        # Actual Transpiration
        act_transpir_layer = ks_layer * pot_transpir_layer

        # Water Mass Balance  ############
        theta_layer -= act_transpir_layer / depth  # [-]

        # Evaporation
        # Evaporation reduction parameter
        # Note: moisture content of air-dry soil = 0.33 * theta_wp [@Allen 1998 in @Sheikh2009]
        # TODO: adjust so that the first 0.15 m of soil depth exhibit evaporation (i.e. not only the first layer)
        if layer < 2:  # No evaporation in deeper layers
            kr_layer = max(scalar(0), min(1, (theta_layer - 0.33 * theta_wp) / (theta_fcap - 0.33 * theta_wp)))

            # TODO: Verify:
            # Not sure why Samuel is using thetaR below instead of Field Capacity
            # thetaR_D0=theta_critical_z0;
            # kr_z0=max(0,min(1,(theta_temp_z0-0.5*theta_wp)/(thetaR_D0-0.5*theta_wp)));

            # Actual Evaporation
            act_evaporation_layer = ifthenelse((theta_layer * depth) < (kr_layer * pot_evapor),
                                               theta_layer * depth, kr_layer * pot_evapor)

            if layer == 1:
                act_evaporation_layer *= 0.5  # Act only on half of the second layer.

            # model.report(act_evaporation_layer, 'aObj1')
            # model.report(act_evaporation_layer, 'aObj2')

            # Actual evapotranspiration
            # ETact_D0 = act_evaporation_z0 + act_transpir_z0
            # Update soil moisture after evapotranspiration
            theta_layer -= act_evaporation_layer / depth
            # theta_temp_z0=max(theta_temp_z0,0.05);
        else:
            act_evaporation_layer = model.zero_map

        # Final update (change in storage)
        # theta_change_mm = (theta_layer * depth) - theta_ini_mm

        etp_layer = act_evaporation_layer + act_transpir_layer
    else:
        etp_layer = model.zero_map

    if model.currentTimeStep() % 2 == 0:
        model.report(etp_layer, 'aETP')

    return {"theta_ini": theta_ini,  # initial moisture
            "theta_final": theta_layer,  # final moisture
            "infil": infil,
            "percolate": deep_percolation,  # mm percolated to lower layer
            "theta_after_percolate": theta_after_percolate,
            "satex": satex,
            "runoff": roff_z0,  # mm
            "drain_lat_outflow": cell_drainge_outflow,  # mm
            "lat_flow": lateral_flow_layer,  # net mm
            "overflow_height": overflow_height,  # mm
            "ETP": etp_layer,
            "balance": water_balance_layer,
            "upstream_lat_inflow": upstream_cell_inflow,
            "cell_lat_outflow": cell_moisture_outflow
            }


def getLayerTemp(model, layer,
                 bio_cover, temp_bare_soil
                 ):
    layer_params = {'depth': 'model.z' + str(layer), # delete!
                    'theta': 'model.theta_z' + str(layer),
                    'temp_lagged': 'model.temp_z' + str(layer) + '_fin'}

    depth = model.layer_depth[layer]  # eval(layer_params['depth'])
    theta = eval(layer_params['theta'])
    temp_lagged = eval(layer_params['temp_lagged'])

    # Step 1: Defining the soil column's center to damping depth ratio.
    # Scaling factor (phi), adjusts the impact of soil water content (SW = theta*depth) on damping depth (dd)
    # layer, yes
    phi_layer = (theta * depth) / ((0.356 - 0.144 * model.p_b) * model.tot_depth)

    # Daily value of the damping depth (dd), (mm):
    # layer, yes
    dd_layer = model.dd_max * exp(ln(500 / model.dd_max) * ((1 - phi_layer) / (1 + phi_layer)) ** 2)

    # Soil column's center to damping depth ratio (zd), (-):
    zd_layer = (depth * 0.5) / dd_layer

    # Step 2: Calculating soil surface depth
    # Depth factor quantifies the influence of depth below surface on soil temperature:
    df_layer = zd_layer / (zd_layer + exp(-0.867 - 2.708 * zd_layer))

    # Need to define temp_soil_surf_fin, if layer > 0
    if DEBUG:
        if layer == 0:
            # Define surface temperature when no cover is present:
            temp_at_surf = bio_cover * model.temp_surf_fin + (1 - bio_cover) * temp_bare_soil

            # model.report(phi_layer, "phi")
            # model.report(dd_layer, "ddTemp")
            # model.report(dd_layer, "dfTemp")
            model.report(temp_at_surf, "tempSrf")
            model.report(bio_cover, "bioCV")
            # model.report(temp_bare_soil, "bareTSo")


    else:
        temp_at_surf = model.temp_surf_fin

    # Soil layer 1 temperature is finally:
    temp_soil_layer = model.lag * temp_lagged + (1 - model.lag) * \
                                                (df_layer * (model.temp_ave_air - temp_at_surf) + temp_at_surf)
    # Next period's update:
    return {"temp_layer": temp_soil_layer, "temp_surface": temp_at_surf}


def getPotET(model, sow_yy, sow_mm, sow_dd,
             jd_sim,
             wind, humid,
             # frac_soil_cover, # Replaced by method: Allen et al., 1998
             et0,
             kcb_ini, kcb_mid, kcb_end,
             height,
             len_grow_stage_ini, len_dev_stage, len_mid_stage, len_end_stage,
             p_tab):
    # In: Sheikh2009
    # Based on:
    # Allen1998: Simplified version of the Penman–Monteith (FAO56) approach:
    # Allen, R.G., Pereira, L.S., Raes, D., Smith, M., 1998.
    # Crop evapotranspiration: guidelines for computing cropwater requirements.
    # In: Irrigation and Drainage. Paper 56. FAO, Rome.
    ################

    # Update sowing date / plant date
    jd_plant = convertJulian(sow_yy, sow_mm, sow_dd)

    jd_dev = jd_plant + len_grow_stage_ini
    jd_mid = jd_dev + len_dev_stage
    jd_late = jd_mid + len_mid_stage
    jd_end = jd_late + len_end_stage

    # Basal crop coefficient (defined in crop.tbl)
    # model.report(jd_sim, 'jd_sim')
    # model.report(jd_plant, 'jd_plan')

    kcb_ini = max(kcb_ini, scalar(0.15))  # Kcb_min
    kcb1 = ifthenelse(jd_sim < jd_plant, kcb_ini,
                      ifthenelse(jd_sim < jd_dev, kcb_ini,
                                 ifthenelse(jd_sim < jd_mid,
                                            kcb_ini + (jd_sim - jd_dev) / len_dev_stage * (kcb_mid - kcb_ini),
                                            ifthenelse(jd_sim < jd_late, kcb_mid,
                                                       ifthenelse(jd_sim < jd_end,
                                                                  kcb_mid + (jd_sim - jd_late) / len_end_stage * (
                                                                      kcb_end - kcb_mid),
                                                                  kcb_ini)))))
    # Crop transpiration coefficient adjusted for climate condition, # eq. 72
    kcb = ifthenelse(kcb1 > 0.4, kcb1 + (0.04 * (wind - 2) - 0.004 * (humid - 45)) * (height / 3) ** 0.3, kcb1)
    kcmax = max((1.2 + (0.04 * (wind - 2) - 0.004 * (humid - 45)) * (height / float(3)) ** 0.3), kcb + 0.05)
    # TODO: Remove printouts
    # model.report(kcb, 'akcb')
    # model.report(kcb1, 'akcb1')
    # model.report(kcmax, 'akcmax')
    # Pot. Transpiration
    # Due to Allen et al., 1998
    kcb_ratio = max((kcb - kcb_ini) / (kcmax - kcb_ini), scalar(0))
    frac_soil_cover = min((kcb_ratio) ** (height * 0.5 + 1), scalar(0.99))
    # frac_soil_cover = ifthenelse(kcmax > kcb_ini, ((kcb - kcb_ini) / (kcmax - kcb_ini)) ** (height*0.5 + 1), scalar(0))
    # model.report(kcb, 'kcb')
    # model.report(kcb_ini, 'kcb_ini')
    # model.report(kcmax, 'kc_max')
    # model.report(height, 'kheight')
    # model.report(frac_soil_cover, 'fsoilCV')
    pot_transpir = kcb * et0

    # Pot. Evaporation
    # ke = min((kcmax-kcb),(1-f)*kcmax);
    # ke=1.10;
    ke = kcmax - kcb
    pot_evapor = ke * et0

    # Potential Evapo-transpiration
    pot_et = pot_transpir + pot_evapor

    # Total available soil water that can be depleted from the root
    # zone before moisture stress starts
    depletable_water = p_tab + 0.04 * (5 - pot_et)
    dictionary = {"Tp": pot_transpir, "Ep": pot_evapor, "P": depletable_water, "f": frac_soil_cover}
    return dictionary
