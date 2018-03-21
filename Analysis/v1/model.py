# -*- coding: utf-8 -*-

# from time import *
import time
from datetime import datetime
from hydro import *
from pesti import *

from pcraster._pcraster import *
from pcraster.framework import *
import os

print(os.getcwd())


class BeachModel(DynamicModel):
    def setDebug(self):
        pass

    def __init__(self, cloneMap):
        DynamicModel.__init__(self)
        setclone(cloneMap)

        # dem = self.dem

    def initial(self):
        """ Physical parameters """
        self.c1 = 0.25  # subsurface flow coefficient
        self.c2 = 0.25  # not used (second layer)
        self.drain_coef = 0.8063  # drainage coefficient
        self.s1 = 1  # coefficient to calibrate Ksat1
        self.s2 = 0.5  # coefficient to calibrate Ksat2
        self.k = 0.03  # coefficient of declining LAI in end stage

        """ Soil Properties """
        self.p_b = 1.4  # Soil bulk density (g/cm^3)
        self.f_oc = 0.021  # Organic Carbon in soil without grass (kg/kg)

        """
        Sorption parameters
        """
        # K_oc - S-metolachlor (K_oc in ml/g)
        # Marie's thesis: log(K_oc)= 1.8-2.6 [-] -> k_oc = 63 - 398 (Alletto et al., 2013).
        # Pesticide Properties Database: k_oc = 120 ml/g (range: 50-540 mL/g)
        self.k_oc = 120  # ml/g
        self.k_d = self.k_oc * self.f_oc  # Dissociation coefficient K_d (mL/g = L/Kg)

        # Pesticide Properties Database states :
        # K_d=0.67; but here
        # K_d=120*0.021 = 2.52;  (L/kg)
        # Difference will lead to higher retardation factor (more sorption)

        """
        Volatilization parameters
        """
        # Henry's constant @ 20 C (dimensionless, Metolachlor)
        # https://www.gsi-net.com
        self.k_h = 3.1326141504e-008

        """
        Degradation parameters
        """
        # Half-lives
        # DT50 (typical) = 90
        # DT50 (lab at 20°C) = 15 (range: 8-38 days)
        # DT50 (field) = 21 (range 11-31 Switzerland and France)
        # DT50 (foliar) = 5
        # DT50 (water-sediment) = 365
        # DT50 (water phase only) = 88
        self.dt_50_ref = 15  # S-met (days)

        self.temp_ref = 20  # Temp.  reference

        self.beta_temperature = 1  # Need to find a correct value for 'B', exponent in moisture dependency (Dairon)
        self.alpha_temperature = 54000 / float(8314)  # Need to confirm units Ea = 54000 KJ/mol; R = 8.314 J/mol/Kelvin

        """
        Isotopes
        """
        # VPDB
        self.r_standard = 0.0112372
        self.alpha_iso = 1  # 1 = no fractionation

        """
        Loading maps
        """

        """
        Landscape & Hydro Maps
        """
        self.dem = self.readmap("dem_slope")  # 192 - 231 m a.s.l
        self.dem_route = self.readmap("dem_ldd")  # To route surface run-off
        self.zero_map = self.dem - self.dem  # Zero map to generate scalar maps
        mask = self.dem / self.dem

        # self.ldd_surf = lddcreate(self.dem_route, 1e31, 1e31, 1e31, 1e31)  # To route runoff
        self.ldd_subs = lddcreate(self.dem, 1e31, 1e31, 1e31, 1e31)  # To route lateral flow & build TWI

        self.datum_depth = (self.dem - mapminimum(self.dem)) * scalar(10 ** 3)  # mm
        self.z0 = self.zero_map + 10  # mm
        self.z1 = self.zero_map + 140  # mm
        self.z2 = self.datum_depth + 300 - self.z0 - self.z1  # mm (150mm at outlet)
        self.tot_depth = self.z0 + self.z1 + self.z2


        # Initial moisture (arbitrary, Oct, 2015)
        self.theta_z0 = self.zero_map + 0.4  # map of initial soil moisture in top layer (-)
        self.theta_z1 = self.zero_map + 0.4
        self.theta_z2 = self.zero_map + 0.4

        # Need initial states to compute change in storage after each run
        self.theta_z0_ini = self.theta_z0
        self.theta_z1_ini = self.theta_z1
        self.theta_z2_ini = self.theta_z2

        self.outlet = self.readmap("outlet_true")

        # TODO: temporary fix to landuse.map with holes!!!
        self.landuse = self.readmap("fields_cover")

        # Topographical Wetness Index
        self.cell_area = 4
        self.up_area = accuflux(self.ldd_subs, self.cell_area)
        self.slope = sin(atan(max(slope(self.dem), 0.001)))  # Slope in radians
        self.wetness = ln(self.up_area / tan(self.slope))



        """
        Pesticides Maps
        """
        # Mass
        # in ug/m2 = conc. (ug/g soil) * density (g/cm3) * (10^6 cm3 / m3) * (1 m/10^3 mm) * depth_layer (mm)
        self.smback_z0 = (self.zero_map + 0.06) * self.p_b * scalar(
            10 ** 6 / 10 ** 3) * self.z0  # Based on detailed soils
        self.smback_z1 = (self.zero_map + 0.03) * self.p_b * scalar(
            10 ** 6 / 10 ** 3) * self.z1  # Based on detailed soils
        self.smback_z2 = (self.zero_map + 0.00001) * self.p_b * scalar(10 ** 6 / 10 ** 3) * self.z2  # Assumed

        # Carbon Delta (Background)
        # Assumed theoretical max @99% deg Streitwieser Semiclassical Limits
        self.delta_z0 = self.zero_map - 23.7
        self.delta_z0_ini = self.delta_z0
        self.delta_z1 = self.zero_map - 23.7
        self.delta_z1_ini = self.delta_z1
        self.delta_z2 = self.zero_map - 23.7
        self.delta_z2_ini = self.delta_z2

        # Applications Mass
        # Product concentration (active ing.)
        double = 2.0  # ~ Dosage for corn when growing beet
        d_gold = 915 * 10 ** 6  # ug/L S-met
        m_gold = 960 * 10 ** 6  # ug/L

        # Dosages # L/Ha * 1Ha/1000m2 = L/m2
        d_beet = None
        d_corn = 2.1 * 1 / 10 ** 4  # L/Ha * 1 Ha / 10000 m2
        m_beet = 0.6 * 1 / 10 ** 4 * double
        m_corn = 2.0 * 1 / 10 ** 4
        m_beet_Friess = 0.6 * 1 / 10 ** 4 * (double + 1)  # (Likely larger dosage, early in the season)
        m_beet_Mathis = 0.6 * 1 / 10 ** 4 * (double + 1)  # (Likely larger dosage, early in the season)

        # Assign dosages based on Farmer-Crop combinations [ug/m2]
        fa_cr = readmap("farmer_crop")  # Contains codes to assign appropriate dosage
        app_conc = (  # [ug/m2]
            ifthenelse(fa_cr == 1111,  # 1111 (Friess, Beet)
                       m_beet_Friess * m_gold * mask,
                       ifthenelse(fa_cr == 1122,  # 1112 (Friess-Corn),
                                  m_corn * m_gold * mask,
                                  ifthenelse(fa_cr == 1212,  # 1212 (Speich-Corn),
                                             m_corn * m_gold * mask,
                                             ifthenelse(fa_cr == 1312,  # 1312 (Mahler-Corn),
                                                        m_corn * m_gold * mask,
                                                        ifthenelse(fa_cr == 1412,  # 1412 (Schmitt-Corn)
                                                                   d_corn * d_gold * mask,
                                                                   ifthenelse(fa_cr == 1511,  # 1511 (Burger-Beet)
                                                                              m_beet * m_gold * mask,
                                                                              # 1711 (Mathis-Beet),
                                                                              ifthenelse(fa_cr == 1711,
                                                                                         m_beet_Mathis * m_gold * mask,
                                                                                         # 1611 (Kopp-Beet)
                                                                                         ifthenelse(
                                                                                             fa_cr == 1611,
                                                                                             m_beet * m_gold * mask,
                                                                                             0 * mask))))))))
        )
        # Pesticide applied (ug/m2) on Julian day 177 (March 25, 2016).
        # March 26th, Friess and Mathis
        self.app1 = ifthenelse(fa_cr == 1111, 1 * app_conc,
                               # 1111 (Friess, Beet), 1112 (Friess-Corn),
                               ifthenelse(fa_cr == 1112, 1 * app_conc,
                                          ifthenelse(fa_cr == 1711, 1 * app_conc,  # 1711 (Mathis-Beet)
                                                     0 * app_conc)))
        # Pesticide applied (ug/m2) on Julian day 197 (April 14, 2016).
        # April 14, Kopp and Burger
        self.app2 = ifthenelse(fa_cr == 1511, 1 * app_conc,  # 1511 (Burger-Beet)
                               ifthenelse(fa_cr == 1611, 1 * app_conc,  # 1611 (Kopp-Beet),
                                          0 * app_conc))

        # Pesticide applied (ug/m2) on Julian day 238 (May 25, 2016).
        # May 25, Schmidt and Speich, and (out of transect): Friess and Mahler
        # Note: Speich and Friess could be 1 week later.
        self.app3 = ifthenelse(fa_cr == 1112, 1 * app_conc,  # 1112 (Friess-Corn)
                               ifthenelse(fa_cr == 1212, 1 * app_conc,  # 1212 (Speich-Corn),
                                          ifthenelse(fa_cr == 1412, 1 * app_conc,  # 1412 (Schmitt-Corn),
                                                     ifthenelse(fa_cr == 1312, 1 * app_conc,  # 1312 (Mahler-Corn)
                                                                0 * app_conc))))

        # Applications delta
        # Use map algebra to produce a initial signature map,
        # ATT: Need to do mass balance on addition of new layer.
        # where app1 > 0, else background sig. (plots with no new mass will be 0)
        self.app1delta = ifthenelse(self.app1 > 0, scalar(-32.3), scalar(-23.7))
        self.app2delta = ifthenelse(self.app2 > 0, scalar(-32.3), scalar(-23.7))
        self.app3delta = ifthenelse(self.app3 > 0, scalar(-32.3), scalar(-23.7))

        # Convert mg/m2 -> mg
        self.pestmass_z0 = self.smback_z0 * self.cell_area  # mg
        self.pestmass_z0_ini = self.pestmass_z0
        self.pestmass_z1 = self.smback_z1 * self.cell_area  # mg
        self.pestmass_z1_ini = self.pestmass_z1
        self.pestmass_z2 = self.smback_z2 * self.cell_area  # mg
        self.pestmass_z2_ini = self.pestmass_z2

        # Cumulative maps
        self.pest_ini_storage_mg = self.pestmass_z0_ini + self.pestmass_z1_ini + self.pestmass_z2_ini
        self.cum_appl_mg = self.zero_map
        self.cum_runoff_mg = self.zero_map
        self.cum_leached_mg_z2 = self.zero_map  # Only bottom-most layer needed
        self.cum_latflux_mg_z0 = self.zero_map
        self.cum_latflux_mg_z1 = self.zero_map
        self.cum_latflux_mg_z2 = self.zero_map

        """
        Temperature maps and params
        """
        self.lag = 0.8  # lag coefficient (-), 0 < lag < 1; -> in SWAT, lag = 0.80
        # Generating initial surface temp map (15 deg is arbitrary)
        self.temp_z0_fin = self.zero_map + 15
        self.temp_z1_fin = self.zero_map + 15
        self.temp_z2_fin = self.zero_map + 15
        self.temp_surf_fin = self.zero_map + 15

        # Maximum damping depth (dd_max)
        # The damping depth (dd) is calculated daily and is a function of max. damping depth (dd_max), (mm):
        self.dd_max = (2500 * self.p_b) / (self.p_b + 686 * exp(-5.63 * self.p_b))

        # TODO
        # Average Annual air temperature (celcius - Layon!! Not Alteckendorf yet!!)
        self.temp_ave_air = 12.2  # 12.2 is for Layon

        """
        Output & Observations (tss and observation maps)
        """
        # Output time series (tss)

        # Outlet
        ###########
        # Pesticide
        self.global_mb_pest_tss = TimeoutputTimeseries("res_global_mb_pest", self, nominal("outlet_true"), noHeader=False)
        self.out_delta_tss = TimeoutputTimeseries("out_delta", self, nominal("outlet_true"), noHeader=False)
        self.out_mass_tss = TimeoutputTimeseries("out_mass", self, nominal("outlet_true"), noHeader=False)

        # Hydro
        self.tot_rain_m3_tss = TimeoutputTimeseries("res_accuRain_m3", self, nominal("outlet_true"), noHeader=False)
        self.out_vol_m3_tss = TimeoutputTimeseries("res_accuVol_m3", self, nominal("outlet_true"), noHeader=False)
        self.out_runoff_m3_tss = TimeoutputTimeseries("res_accuRunoff_m3", self, nominal("outlet_true"), noHeader=False)
        self.out_latflow_m3_tss = TimeoutputTimeseries("res_outLatflow_m3", self, nominal("outlet_true"), noHeader=False)
        # self.out_percol_m3_tss = TimeoutputTimeseries("res_outPercol_m3", self, nominal("outlet_true"), noHeader=False)
        self.out_percol_z2_m3_tss = TimeoutputTimeseries("res_accuPercol_z2_m3", self, nominal("outlet_true"), noHeader=False)
        self.out_etp_m3_tss = TimeoutputTimeseries("res_accuEtp_m3", self, nominal("outlet_true"), noHeader=False)
        self.out_ch_storage_m3_tss = TimeoutputTimeseries("res_accuChStorage_m3", self, nominal("outlet_true"), noHeader=False)
        self.global_mb_water_tss = TimeoutputTimeseries("res_global_waterMB", self, nominal("outlet_true"), noHeader=False)



        # Transects and detailed soils
        ###########
        # self.obs_trans = self.readmap("weekly_smp")
        # self.obs_detail = self.readmap("detailed_smp")

        # self.obs_runoff_m3_tss = TimeoutputTimeseries("obs_runoff_m3", self, ordinal("weekly_ord.map"), noHeader=False)
        # self.obs_cum_runoff_m3_tss = TimeoutputTimeseries("obs_runoff_m3_cum", self, ordinal("weekly_ord.map"), noHeader=False)
        # self.obs_latflow_m3_tss = TimeoutputTimeseries("obs_latflow_m3", self, "weekly_smp.map", noHeader=False)
        # self.obs_percol_m3_tss = TimeoutputTimeseries("obs_percol_m3", self, "weekly_smp.map", noHeader=False)
        # self.obs_etp_m3_tss = TimeoutputTimeseries("obs_etp_m3", self, "weekly_smp.map", noHeader=False)
        # self.obs_ch_storage_m3_tss = TimeoutputTimeseries("obs_chStorage_m3", self, "weekly_smp.map", noHeader=False)



        """
        Simulation start time: Oct 1st, 2015
        """
        yy = scalar(2015)
        mm = scalar(10)
        dd = scalar(1)

        date_factor = 1
        if (100 * yy + mm - 190002.5) < 0:
            date_factor = -1

        # simulation start time in JD (Julian Day)
        self.jd_start = 367 * yy - rounddown(7 * (yy + rounddown((mm + 9) / 12)) / 4) + rounddown(
            (275 * mm) / 9) + dd + 1721013.5 - 0.5 * date_factor
        self.jd_cum = 0
        self.jd_dt = 1  # Time step size (days)

    def dynamic(self):
        jd_sim = self.jd_start + self.jd_cum
        fields = timeinputscalar('landuse.tss', nominal(self.landuse))

        # SEE: http://pcraster.geo.uu.nl/pcraster/4.1.0/doc/manual/op_timeinput....html?highlight=timeinputscalar
        # returns value of land-use field (i.e. n = 22), per time step. (Layon)
        # So, at dt = 1
        # fields's values: 98 98	98	98	98	98	98	98	98	98	98	98	13	98	15	99	99	99	99	99	99	98

        " Crop Parameters "
        # SEE: http://pcraster.geo.uu.nl/pcraster/4.1.0/doc/manual/op_lookup.html?highlight=lookupscalar
        setglobaloption('matrixtable')  # allows lookupscalar to read more than 2 expressions.
        crop_type = lookupscalar('croptable.tbl', 1, fields)  # (table, col-value, row-value)
        sow_yy = lookupscalar('croptable.tbl', 2, fields)
        sow_mm = lookupscalar('croptable.tbl', 3, fields)  # sowing or Greenup month
        sow_dd = lookupscalar('croptable.tbl', 4, fields)  # sowing day
        len_grow_stage_ini = lookupscalar('croptable.tbl', 5,
                                          fields)  # old: Lini. length of initial crop growth stage
        len_dev_stage = lookupscalar('croptable.tbl', 6, fields)  # Ldev: length of development stage
        len_mid_stage = lookupscalar('croptable.tbl', 7, fields)  # Lmid: length of mid-season stage
        len_end_stage = lookupscalar('croptable.tbl', 8, fields)  # Lend: length of late season stage
        kcb_ini = lookupscalar('croptable.tbl', 9, fields)  # basal crop coefficient at initial stage
        kcb_mid = lookupscalar('croptable.tbl', 10, fields)  # basal crop coefficient at mid season stage
        kcb_end = lookupscalar('croptable.tbl', 11, fields)  # basal crop coefficient at late season stage
        max_LAI = lookupscalar('croptable.tbl', 12, fields)  # maximum leaf area index
        mu = lookupscalar('croptable.tbl', 13, fields)  # light use efficiency
        max_height = lookupscalar('croptable.tbl', 14, fields)  # maximum crop height

        max_root_depth = lookupscalar('croptable.tbl', 15, fields) * 1000  # max root depth converting from m to mm
        # Max RD (m) according to Allen 1998, Table 22 (now using FAO source)
        # Sugar beet = 0.7 - 1.2
        # Corn = 1.0 - 1.7
        # Grazing pasture 0.5 - 1.5
        # Spring Wheat = 1.0 -1.5
        # Winter Wheat = 1.5 -1.8
        # Apple trees = 1.0-2.0

        p_tab = lookupscalar('croptable.tbl', 16,
                             fields)  # depletable theta before water stress (Allen1998, Table no.22)
        # p_tab (-) according to Allen 1998, Table 22 (now using FAO source)
        # Sugar beet = 0.55
        # Corn = 0.55
        # Grazing Pasture = 0.6
        # Spring Wheat = 0.55
        # Winter Wheat = 0.55
        # Apple trees = 0.5

        """ Soil physical parameters """
        # Saturated moisture capacity is equal for depth0 and depth1
        theta_sat_z0z1 = lookupscalar('croptable.tbl', 17, fields)  # saturated moisture of the first layer # [-]
        theta_fcap_z0z1 = lookupscalar('croptable.tbl', 18,
                                       fields)  # field capacity of 1st layer (equal for D0 and k=1)
        theta_sat_z2 = lookupscalar('croptable.tbl', 19, fields)  # saturated moisture of 2nd layer
        theta_fcap_z2 = lookupscalar('croptable.tbl', 20, fields)  # field capacity of the 2nd layer
        theta_wp = lookupscalar('croptable.tbl', 21, fields)  # wilting point moisture
        k_sat_z0z1 = lookupscalar('croptable.tbl', 22, fields)  # saturated conductivity of the first layer
        k_sat_z2 = lookupscalar('croptable.tbl', 23, fields)  # saturated conductivity of the second layer
        CN2 = lookupscalar('croptable.tbl', 24, fields)  # curve number of moisture condition II

        # adjusting K_sat
        k_sat_z0z1 *= self.s1
        k_sat_z2 *= self.s2

        """
        Time-series data to spatial location,
        map is implicitly defined as the clonemap.
        """
        precip = timeinputscalar('rain.tss', 1)  # daily precipitation data as time series (mm)
        temp_bare_soil = timeinputscalar('T_bare.tss', nominal('clone_nom'))  # SWAT, Neitsch2009, p.43.
        temp_air = timeinputscalar('airTemp.tss', nominal('clone_nom'))
        et0 = timeinputscalar('ET0.tss', 1)  # daily ref. ETP at Zorn station (mm)
        wind = timeinputscalar('U2.tss', 1)  # wind speed time-series at 2 meters height
        humid = timeinputscalar('RHmin.tss', 1)  # minimum relative humidity time-series # PA: (-)
        # precipVol = precip * cellarea() / 1000  # m3



        ################
        # Crop growth ##
        ################
        jd_sow = convertJulian(sow_yy, sow_mm, sow_dd)
        all_stages = len_grow_stage_ini + len_dev_stage + len_mid_stage + len_end_stage

        # updating of sowing date by land use
        sow_yy = ifthenelse(jd_sim < jd_sow + all_stages, sow_yy,
                            ifthenelse(jd_sim < jd_sow + all_stages + 365, sow_yy + 1,
                                       ifthenelse(jd_sim < jd_sow + all_stages + 730, sow_yy + 2,
                                                  ifthenelse(jd_sim < jd_sow + all_stages + 1095, sow_yy + 3,
                                                             ifthenelse(jd_sim < jd_sow + all_stages + 1460,
                                                                        sow_yy + 4,
                                                                        scalar(0))))))

        # Update sowing date / plant date
        jd_plant = convertJulian(sow_yy, sow_mm, sow_dd)

        jd_dev = jd_plant + len_grow_stage_ini
        jd_mid = jd_dev + len_dev_stage
        jd_late = jd_mid + len_mid_stage
        jd_end = jd_late + len_end_stage
        LAIful = max_LAI + 0.5

        # calculation of crop height
        height = ifthenelse(crop_type > scalar(1), max_height,
                            ifthenelse(jd_sim < jd_plant, scalar(0),
                                       ifthenelse(jd_sim < jd_mid + 0.5 * len_mid_stage,
                                                  max_height * (jd_sim - jd_plant) / (
                                                      len_grow_stage_ini + len_dev_stage + 0.5 * len_mid_stage), \
                                                  ifthenelse(jd_sim < jd_end, max_height,
                                                             0))))
        # calculation of root depth
        # TODO: Check first argument is correct, find documentation for root depth & height
        root_depth = ifthenelse(crop_type > scalar(1), max_root_depth,
                                ifthenelse(jd_sim < jd_plant, scalar(0),
                                           ifthenelse(jd_sim < jd_mid + len_mid_stage / 2,
                                                      max_root_depth * (jd_sim - jd_plant) / (
                                                          len_grow_stage_ini + len_dev_stage + len_mid_stage / 2),
                                                      ifthenelse(jd_sim < jd_end, max_root_depth,
                                                                 scalar(0)))))

        # root dispersal for each soil layer (z)
        root_depth_z0 = ifthenelse(root_depth > self.z0, self.z0, root_depth)
        root_depth_z1 = ifthenelse(root_depth < self.z1, scalar(0),
                                   ifthenelse(root_depth < self.z1 + self.z0, root_depth - self.z0, self.z1))
        root_depth_z2 = ifthenelse(root_depth <= self.z0 + self.z1, scalar(0),
                                   ifthenelse(root_depth < self.tot_depth, root_depth - self.z1 - self.z0, self.z2))

        # calculation of leaf area index
        LAI = ifthenelse(jd_sim < jd_plant, scalar(0),
                         ifthenelse(jd_sim < jd_mid,
                                    max_LAI * (jd_sim - jd_plant) / (len_grow_stage_ini + len_dev_stage),
                                    ifthenelse(jd_sim < jd_mid + 0.5 * len_mid_stage,
                                               max_LAI + (LAIful - max_LAI) * (jd_sim - jd_mid) / (
                                                   0.5 * len_mid_stage),
                                               ifthenelse(jd_sim < jd_late, LAIful,
                                                          ifthenelse(jd_sim <= jd_end,
                                                                     LAIful * exp(
                                                                         -self.k * (jd_sim - jd_late)),
                                                                     scalar(0))))))
        # calculation of fraction of soil covered by vegetation
        # frac_soil_cover = 1 - exp(-mu * LAI)
        # \mu is a light-use efficiency parameter that
        # depends on land-use characteristics
        # (i.e. Grass: 0.35; Crops: 0.45; Trees: 0.5-0.77; cite: Larcher, 1975).

        # TODO: Check "f" definition by Allan et al., 1998 against previous (above)
        # fraction of soil cover is calculated inside the "getPotET" function.
        # frac_soil_cover = ((Kcb - Kcmin)/(Kcmax - Kcmin))**(1+0.5*mean_height)
        # self.fTss.sample(frac_soil_cover)

        # Get potential evapotranspiration for all layers
        etp_dict = getPotET(sow_yy, sow_mm, sow_dd,
                            jd_sim,
                            wind, humid,
                            et0,
                            kcb_ini, kcb_mid, kcb_end,
                            height,
                            len_grow_stage_ini, len_dev_stage, len_mid_stage, len_end_stage,
                            p_tab)
        pot_transpir = etp_dict["Tp"]
        pot_evapor = etp_dict["Ep"]
        depletable_water = etp_dict["P"]

        # Not in use for water balance, but used to estimate surface temp due to bio-cover.
        frac_soil_cover = etp_dict["f"]
        bio_cover = getBiomassCover(self, frac_soil_cover)

        ######################################################################################
        # Mixing layer: depth z0
        # State functions
        #########################
        # Temperature, z0
        temp_dict_z0 = getLayerTemp(self, 0, bio_cover, temp_bare_soil)
        self.temp_surf_fin = temp_dict_z0["temp_surface"]
        self.temp_z0_fin = temp_dict_z0["temp_layer"]

        #########################
        # Moisture, z0
        self.theta_z0_ini = self.theta_z0

        z0_moisture = getLayerMoisture(self, 0,
                                       precip, theta_wp, CN2, crop_type,
                                       jd_sim, jd_dev, jd_mid, jd_end, len_dev_stage,
                                       root_depth, pot_evapor, pot_transpir, depletable_water,
                                       k_sat_z0z1, root_depth_z0,
                                       theta_fcap_z0z1, theta_sat_z0z1)
        percolation_z0 = z0_moisture["percolate"]
        sat_excess_z0 = z0_moisture["satex"]
        # TODO: verify amounts lost to sub-layer are correct
        tot_percolation_z0 = percolation_z0 + sat_excess_z0
        runoff_z0 = z0_moisture["runoff"]
        etp_z0 = z0_moisture["ETP"]
        # Report the discharge map
        # discharge = accuflux(self.ldd, runoff_z0)
        # self.report(discharge, "dt" + str(self.jd_cum) + "discharge.map")
        lat_flow_z0 = z0_moisture["lat_flow"]
        lat_outflow_z0 = z0_moisture["cell_lat_outflow"]

        # self.obs_runoff_m3_tss.sample(runoff_z0*4/1000)



        #########################
        # Mass Transfer, z0
        mass_loss_dt_z0 = 0
        mass_gain_dt_z0 = 0

        # Background and applications
        self.pestmass_z0_ini = self.pestmass_z0  # mg

        mass_applied = ifthenelse(self.jd_cum == 177,
                                  self.app1 * self.cell_area,
                                  ifthenelse(self.jd_cum == 197, self.app2 * self.cell_area,
                                             ifthenelse(self.jd_cum == 238, self.app3 * self.cell_area,
                                                        0)))  # [mg]
        self.cum_appl_mg += mass_applied
        self.pestmass_z0 += mass_applied  # mg
        mass_loss_dt_z0 += 0
        mass_gain_dt_z0 += mass_applied

        # Isotopes change due to applications
        self.delta_z0_ini = self.delta_z0
        delta_applied = ifthenelse(self.jd_cum == 177, self.app1delta,
                                   ifthenelse(self.jd_cum == 197, self.app2delta,
                                              ifthenelse(self.jd_cum == 238, self.app3delta,
                                                         0)))  # [delta permille]
        # isotope mass balance (due to application only)
        self.delta_z0 = 1 / self.pestmass_z0 * (
            self.delta_z0_ini * self.pestmass_z0_ini + delta_applied * mass_applied)

        # Mass & delta volatilized
        mass_before_transport = self.pestmass_z0
        z0_mass_volatilized = getVolatileMass(self, [177, 197, 238],  # Application days
                                              temp_air, theta_sat_z0z1,
                                              rel_diff_model='option-1', sorption_model="linear",
                                              gas=True)
        self.pestmass_z0 -= z0_mass_volatilized["mass_loss"]
        self.delta_z0 = update_layer_delta(self, 0, "volat", z0_mass_volatilized, mass_before_transport)

        # TODO: Mass loss due to plant uptake!

        # Mass & delta run-off (RO)
        mass_before_transport = self.pestmass_z0
        # transfer_model = "d-mlm"
        z0_mass_runoff = getRunOffMass(self, theta_sat_z0z1,
                                       precip, runoff_z0,
                                       transfer_model="d-mlm", sorption_model="linear")
        self.pestmass_z0 -= z0_mass_runoff["mass_runoff"]  # mg
        self.delta_z0 = update_layer_delta(self, 0, "runoff", z0_mass_runoff, mass_before_transport)

        # Mass & delta leached (Deep Percolation - DP)
        z0_mass_leached = getLeachedMass(self, 0, theta_sat_z0z1,
                                         precip,
                                         tot_percolation_z0,
                                         z0_moisture["theta_after_percolate"],
                                         sorption_model="linear",
                                         leach_model="mcgrath")
        mass_before_transport = self.pestmass_z0
        self.pestmass_z0 -= z0_mass_leached["mass_leached"]  # mg
        self.delta_z0 = update_layer_delta(self, 0, "leach", z0_mass_leached, mass_before_transport)

        # Mass & delta latflux (LF)
        z0_mass_latflux = getLateralMassFlux(self, 0, theta_sat_z0z1, theta_fcap_z0z1)
        mass_before_transport = self.pestmass_z0
        self.pestmass_z0 += z0_mass_latflux["net_mass_latflux"]  # mg
        self.delta_z0 = update_layer_delta(self, 0, "latflux", z0_mass_latflux, mass_before_transport)

        # Degradation
        mass_before_degradation = self.pestmass_z0
        deg_z0_dict = degrade(self, 0,
                              theta_sat_z0z1, theta_sat_z2,
                              theta_fcap_z0z1, theta_wp,
                              sor_deg_factor=1)
        self.pestmass_z0 = deg_z0_dict["mass_light_fin"] + deg_z0_dict["mass_heavy_fin"]
        self.delta_z0 = (deg_z0_dict["mass_heavy_fin"] / deg_z0_dict[
            "mass_light_fin"] - self.r_standard) / self.r_standard

        # # Testing
        # if self.jd_cum in {2, 5, 8}:
        #     t0 = time.time()
        #     self.report(self.delta_z1, "dz0_" + str(self.jd_cum))
        #     t1 = time.time()
        #     print("Total:", t1 - t0)

        # Update state variables
        # Change in storage - Moisture
        self.theta_z0 = z0_moisture["theta_final"]
        ch_storage_z0_m3 = (self.theta_z0 * self.z0 * 4 / 1000) - \
                           (self.theta_z0_ini * self.z0 * 4 / 1000)
        self.theta_z0_ini = self.theta_z0

        # Change in mass storage after degradation - Pesticide Mass
        ch_storage_z0_mg = self.pestmass_z0 - self.pestmass_z0_ini
        self.pestmass_z0_ini = self.pestmass_z0

        # Cumulative
        self.cum_runoff_mg += z0_mass_runoff["mass_runoff"]
        self.cum_latflux_mg_z0 += z0_mass_latflux["net_mass_latflux"]

        #self.theta_z0tss.sample(self.theta_z0)
        #self.water_balance_z0tss.sample(z0_moisture["balance"])

        #######################################################################################
        # Layer z = 1

        # State functions
        # Temperature
        temp_dict_z1 = getLayerTemp(self, 1, bio_cover, temp_bare_soil)
        self.temp_z1_fin = temp_dict_z1["temp_layer"]
        # Moisture
        z1_moisture = getLayerMoisture(self, 1,
                                       precip, theta_wp, CN2, crop_type,
                                       jd_sim, jd_dev, jd_mid, jd_end, len_dev_stage,
                                       root_depth, pot_evapor, pot_transpir, depletable_water,
                                       k_sat_z0z1, root_depth_z1,
                                       theta_fcap_z0z1, theta_sat_z0z1,
                                       percolate=percolation_z0, satex=sat_excess_z0)
        percolation_z1 = z1_moisture["percolate"]
        lat_flow_z1 = z1_moisture["lat_flow"]
        lat_outflow_z1 = z1_moisture["cell_lat_outflow"]
        etp_z1 = z1_moisture["ETP"]

        #########################
        # Mass Transfer, z1
        # Mass volatilized = not relevant @z1!
        # Mass runoff = not relevant @z1!
        # Mass & delta leached (Deep Percolation - DP, z1)
        self.pestmass_z1 += z0_mass_leached["mass_leached"]
        z1_mass_leached = getLeachedMass(self, 1, theta_sat_z0z1,
                                         precip,
                                         percolation_z1,
                                         z1_moisture["theta_after_percolate"],
                                         sorption_model="linear")
        mass_before_transport = self.pestmass_z1
        self.pestmass_z1 -= z1_mass_leached["mass_leached"]
        self.delta_z1 = update_layer_delta(self, 1, "leach", z1_mass_leached, mass_before_transport)

        # Mass & delta latflux (LF), z1
        z1_mass_latflux = getLateralMassFlux(self, 1, theta_sat_z0z1, theta_fcap_z0z1)
        mass_before_transport = self.pestmass_z1
        self.pestmass_z1 += z1_mass_latflux["net_mass_latflux"]
        self.delta_z1 = update_layer_delta(self, 1, "latflux", z1_mass_latflux, mass_before_transport)

        # Degradation
        mass_before_degradation = self.pestmass_z1
        deg_z1_dict = degrade(self, 1,
                              theta_sat_z0z1, theta_sat_z2,
                              theta_fcap_z0z1, theta_wp,
                              sor_deg_factor=1)
        self.pestmass_z1 = deg_z1_dict["mass_light_fin"] + deg_z1_dict["mass_heavy_fin"]
        self.delta_z1 = (deg_z1_dict["mass_heavy_fin"] / deg_z1_dict[
            "mass_light_fin"] - self.r_standard) / self.r_standard

        # Update state variables
        # Change in storage - Moisture
        self.theta_z1 = z1_moisture["theta_final"]
        ch_storage_z1_m3 = (self.theta_z1 * self.z1 * 4 / 1000) - \
                           (self.theta_z1_ini * self.z1 * 4 / 1000)
        self.theta_z1_ini = self.theta_z1

        # Change in storage - Pesticide Mass
        self.conc_z1 = self.pestmass_z1 / (self.theta_z1 * self.z1)  # mg/mm
        ch_storage_z1_mg = self.pestmass_z1 - self.pestmass_z1_ini
        self.pestmass_z1_ini = self.pestmass_z1

        #######################
        # Cumulative counters
        self.cum_latflux_mg_z1 += z1_mass_latflux["net_mass_latflux"]

        # SAVE
        #self.theta_z1tss.sample(self.theta_z1)
        #self.water_balance_z1tss.sample(z1_moisture["balance"])

        #######################################################################################
        # Layer z = 2
        # Temperature
        temp_dict_z2 = getLayerTemp(self, 2, bio_cover, temp_bare_soil)
        self.temp_z2_fin = temp_dict_z2["temp_layer"]
        # Moisture
        z2_moisture = getLayerMoisture(self, 2,
                                       precip, theta_wp, CN2, crop_type,
                                       jd_sim, jd_dev, jd_mid, jd_end, len_dev_stage,
                                       root_depth, pot_evapor, pot_transpir, depletable_water,
                                       k_sat_z2, root_depth_z2,
                                       theta_fcap_z2, theta_sat_z2,
                                       percolate=percolation_z1)

        percolation_z2 = z2_moisture["percolate"]
        lat_flow_z2 = z2_moisture["lat_flow"]
        lat_outflow_z2 = z2_moisture["cell_lat_outflow"]
        etp_z2 = z2_moisture["ETP"]

        #########################
        # Mass Transfer, z2
        # Mass volatilized = not relevant @z2!
        # Mass runoff = not relevant @z2!
        # Mass & delta leached (Deep Percolation - DP, z2)
        self.pestmass_z2 += z1_mass_leached["mass_leached"]
        z2_mass_leached = getLeachedMass(self, 2, theta_sat_z2,
                                         precip,
                                         percolation_z2,
                                         z2_moisture["theta_after_percolate"],
                                         sorption_model="linear")
        mass_before_transport = self.pestmass_z2
        self.pestmass_z2 -= z2_mass_leached["mass_leached"]
        self.delta_z2 = update_layer_delta(self, 2, "leach", z2_mass_leached, mass_before_transport)

        # Mass & delta latflux (LF), z2
        z2_mass_latflux = getLateralMassFlux(self, 2, theta_sat_z2, theta_fcap_z0z1)
        mass_before_transport = self.pestmass_z2
        self.pestmass_z2 += z2_mass_latflux["net_mass_latflux"]
        self.delta_z2 = update_layer_delta(self, 2, "latflux", z2_mass_latflux, mass_before_transport)

        # Degradation
        mass_before_degradation = self.pestmass_z2
        deg_z2_dict = degrade(self, 2,
                              theta_sat_z0z1, theta_sat_z2,
                              theta_fcap_z0z1, theta_wp,
                              sor_deg_factor=1)
        self.pestmass_z2 = deg_z2_dict["mass_light_fin"] + deg_z2_dict["mass_heavy_fin"]
        self.delta_z2 = (deg_z2_dict["mass_heavy_fin"] / deg_z2_dict[
            "mass_light_fin"] - self.r_standard) / self.r_standard

        # Update state variables
        # Change in storage - Moisture
        self.theta_z2 = z2_moisture["theta_final"]
        ch_storage_z2_m3 = (self.theta_z2 * self.z2 * 4 / 1000) - \
                           (self.theta_z2_ini * self.z2 * 4 / 1000)
        self.theta_z2_ini = self.theta_z2

        #self.theta_z2tss.sample(self.theta_z2)
        #self.water_balance_z2tss.sample(z2_moisture["balance"])

        # Change in storage - Pesticide Mass
        self.conc_z2 = self.pestmass_z2 / (self.theta_z2 * self.z2)  # mg/mm
        ch_storage_z2_mg = self.pestmass_z2 - self.pestmass_z2_ini
        self.pestmass_z2_ini = self.pestmass_z2

        #################
        # Cumulative counters
        self.cum_leached_mg_z2 += z2_mass_leached["mass_leached"]
        self.cum_latflux_mg_z2 += z2_mass_latflux["net_mass_latflux"]

        ###########################################################################
        # FINAL MASS BALANCE #
        ######################
        # 'Sample' the time-series associated to each component (e.g. runoff) at the outlet or due to accuflux()

        ######################
        # Water Balance
        ######################
        # Precipitation total
        rain_m3 = precip * 4 / 1000  # m3
        tot_rain_m3 = accuflux(self.ldd_subs, rain_m3)
        self.tot_rain_m3_tss.sample(tot_rain_m3)

        # Discharge due to runoff at the outlet
        runoff_m3 = runoff_z0 * 4 / 1000  # m3
        out_runoff_m3 = accuflux(self.ldd_subs, runoff_m3)
        self.out_runoff_m3_tss.sample(out_runoff_m3)  # save to outlet
        # self.obs_cum_runoff_m3_tss.sample(out_runoff_m3)  # save to sample locations

        # Net lateral flow
        net_latflow_z0_m3 = lat_flow_z0 * 4 / 1000  # m3
        net_latflow_z1_m3 = lat_flow_z1 * 4 / 1000
        net_latflow_z2_m3 = lat_flow_z2 * 4 / 1000
        net_latflow_m3 = net_latflow_z0_m3 + net_latflow_z1_m3 + net_latflow_z2_m3

        # Here accuflux(), why? Bc. have to think of the accumulation of
        # discharge potential that builds by accounting for each cell that is counted
        # in the direction of falling topography. It may seem that each cell is transporting
        # more than its actual capacity, however transport of the total amount takes place across 1 day-length.
        # This is intuitive because discharge begins to take place at the millisecond the day has started,
        # discharge being progressive.
        # Further, the constraints of transfer have been declared (i.e. theta-theta_fc); Updating of theta for each cell
        # is not done until the end of the lateral flow computation, thus
        # every cell transfers to its neighbour only its own potential amount.
        # The cummulative computation is a summary of a whole day's process.
        out_net_latflow_m3 = accuflux(self.ldd_subs, net_latflow_m3)

        # Percolation (only interested in the bottom-most layer, where mass leaves the model)
        percol_z2_m3 = percolation_z2 * 4 / 1000  # m3
        out_percol_m3 = accuflux(self.ldd_subs, percol_z2_m3)
        self.out_percol_z2_m3_tss.sample(out_percol_m3)

        # Evapotranspiration
        etp_z0_m3 = etp_z0 * 4 / 1000  # m3
        etp_z1_m3 = etp_z1 * 4 / 1000
        etp_z2_m3 = etp_z2 * 4 / 1000
        etp_m3 = etp_z0_m3 + etp_z1_m3 + etp_z2_m3
        out_etp_m3 = accuflux(self.ldd_subs, etp_m3)
        self.out_etp_m3_tss.sample(out_etp_m3)

        # Change in storage
        ch_storage_m3 = ch_storage_z0_m3 + ch_storage_z1_m3 + ch_storage_z2_m3
        out_ch_storage_m3 = accuflux(self.ldd_subs, ch_storage_m3)
        self.out_ch_storage_m3_tss.sample(out_ch_storage_m3)

        global_mb_water = tot_rain_m3 - out_runoff_m3 - out_percol_m3 - out_etp_m3 + out_net_latflow_m3 - out_ch_storage_m3
        self.global_mb_water_tss.sample(global_mb_water)

        # Out due to lateral flow
        out_latflow_z0_m3 = lat_outflow_z0 * 4 / 1000  # m3
        out_latflow_z1_m3 = lat_outflow_z1 * 4 / 1000
        out_latflow_z2_m3 = lat_outflow_z2 * 4 / 1000
        out_latflow_m3 = out_latflow_z0_m3 + out_latflow_z1_m3 + out_latflow_z2_m3
        self.out_latflow_m3_tss.sample(out_latflow_m3)

        vol_disch_m3 = out_runoff_m3 + out_latflow_m3
        self.out_vol_m3_tss.sample(vol_disch_m3)

        ######################
        # Pesticide Balance
        ######################
        # Applied mg on catchment
        appl_catch_mg = accuflux(self.ldd_subs, mass_applied)
        cum_appl_catch_mg = accuflux(self.ldd_subs, self.cum_appl_mg)
        # Todo: Check if below same result
        # cum_appl_catch_mg = upstream(self.ldd_subs, self.cum_appl_mg)

        # Loss to run-off
        out_runoff_mg = accuflux(self.ldd_subs, z0_mass_runoff["mass_runoff"])
        cum_out_runoff_mg = accuflux(self.ldd_subs, self.cum_runoff_mg)

        # Loss to air/volatilized
        out_volat_mg = accuflux(self.ldd_subs, z0_mass_volatilized["mass_loss"])
        # cum_out_volat_mg = accuflux(self.ldd, ...)

        # Loss to leaching
        out_leach_mg = accuflux(self.ldd_subs, z2_mass_leached["mass_leached"])
        cum_out_leach_mg = accuflux(self.ldd_subs, self.cum_leached_mg_z2)

        # Loss to lateral flux
        # ... per time step
        mass_latflux_mg = (z0_mass_latflux["net_mass_latflux"] +
                           z1_mass_latflux["net_mass_latflux"] +
                           z2_mass_latflux["net_mass_latflux"])
        out_latflux_mg = accuflux(self.ldd_subs, mass_latflux_mg)
        # ... to date (cumulative)
        tot_latflux_mg = self.cum_latflux_mg_z0 + self.cum_latflux_mg_z1 + self.cum_latflux_mg_z2
        cum_out_latflux_mg = accuflux(self.ldd_subs, tot_latflux_mg)

        # Change in mass storage
        # ... per time step
        ch_storage_mg = ch_storage_z0_mg + ch_storage_z1_mg + ch_storage_z2_mg
        tot_ch_storage_mg = accuflux(self.ldd_subs, ch_storage_mg)
        # ... to date (cumulative)
        cum_ch_storage_mg = ch_storage_mg - self.pest_ini_storage_mg
        cum_tot_ch_storage_mg = accuflux(self.ldd_subs, cum_ch_storage_mg)

        global_mb_pest = appl_catch_mg - out_runoff_mg - out_leach_mg + out_latflux_mg - tot_ch_storage_mg - out_volat_mg
        global_mb_pest_cum = cum_appl_catch_mg - cum_out_runoff_mg - cum_out_leach_mg + cum_out_latflux_mg - cum_tot_ch_storage_mg  # - cum_out_volat_mg
        self.global_mb_pest_tss.sample(global_mb_pest)

        "Write a map for specific time step"
        timeStep = self.currentTimeStep()
        if timeStep == 200:  # April 17 = 200dt
            report(out_runoff_m3, "resdt" + str(timeStep) + "_accu_runoff_m3.map")  # Check against data
            report(runoff_m3, "resdt" + str(timeStep) + "_cell_runoff_m3.map")  # Check ditch results
            report(percolation_z0, "resdt" + str(timeStep) + "_percol_z0.map")  # Check ditch results
            report(percolation_z1, "resdt" + str(timeStep) + "_percol_z1.map")  # Check ditch results
            report(percolation_z2, "resdt" + str(timeStep) + "_percol_z2.map")  # Check ditch results
            # report(nmap, 'zzTest.map')
            # aguila(nmap, self.temp_z0_fin)
            print 'dynamic time step: ', timeStep
        if timeStep == 274:  # June 30
            # Saving initial moisture for v2
            report(self.theta_z0, "resV1" + str(timeStep) + "_theta_z0.map")  # Check ditch results
            report(self.theta_z1, "resV1" + str(timeStep) + "_theta_z1.map")  # Check ditch results
            report(self.theta_z2, "resV1" + str(timeStep) + "_theta_z2.map")  # Check ditch results
            # report(nmap, 'zzTest.map')
            # aguila(nmap, self.temp_z0_fin)
            print 'dynamic time step: ', timeStep

        # Other:
        #
        # report(anim) Disch=accuflux(Ldd, Runoff);

        self.jd_cum += self.jd_dt  # updating JDcum, currently dt = 1 day


firstTimeStep = 1
nTimeSteps = 280
myAlteck16 = BeachModel("clone_nom.map")  # an instance of the model, which inherits from class: DynamicModel
dynamicModel = DynamicFramework(myAlteck16, lastTimeStep=nTimeSteps, firstTimestep=firstTimeStep)  # an instance of the Dynamic Framework

t0 = datetime.now()
dynamicModel.run()
t1 = datetime.now()

duration = t1 - t0
print("Total minutes: ", duration.total_seconds() / 60)
print("Minutes/Yr: ", (duration.total_seconds() / 60)/(nTimeSteps-firstTimeStep)*365)