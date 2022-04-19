# Copyright 2021 VicEdTools authors

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Functions for automating the export of data from VASS."""

from __future__ import annotations

from io import StringIO
import re
import requests
import time
import xml.etree.ElementTree as ET

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.ie.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


def click_with_retry(element: WebElement, test: callable[[], bool]) -> bool:
    """Tries fives times to click a webdriver element, stopping if test passes.
    
    Used to deal with IE driver unreliability.
    
    Args:
        element: A webdriver element.
        test: A function that returns True if click was successful.
    
    Returns:
        Whether click was successful.
    """
    tries = 0
    while tries < 5:
        element.click()
        if test():
            return True
        time.sleep(0.2)
        tries += 1
    return False


def find_window(driver: WebDriver, window_title: str) -> str:
    """Find the window handle with a particular title.
    
    Args:
        driver: A webdriver instance.
        window_title: The window title to locate.
        
    Returns:
        The window handle of the window, if found. Otherwise, None.
    """
    current = driver.current_window_handle
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        if driver.title == window_title:
            driver.switch_to.window(current)
            return handle
    driver.switch_to.window(current)
    return None


def is_menu_item_displayed(driver: WebDriver, xpath_expr: str) -> bool:
    """Tests to see if a given menu item is displayed in VASS.
    
    Used to deal with unreliable clicks in IE.
    
    Args:
        driver: An instance of VASSWebDriver.
        xpath_expr: An xpath expression that matches the menu item.
    """
    cf = current_frame(driver)
    driver.switch_to.default_content()
    driver.switch_to.frame('main')
    menu_item = driver.find_element_by_xpath(xpath_expr)
    is_displayed = menu_item.is_displayed()
    driver.switch_to.default_content()
    driver.switch_to.frame(cf)
    return is_displayed


def current_frame(driver: WebDriver) -> str:
    """Returns the name of the webdriver's current frame."""
    return driver.execute_script("""
            var frame = window.frameElement;
            if (!frame) {
                return 'root of window named ' + document.title;
            }
            return frame.name;
            """)


class VASSWebDriver(webdriver.Ie):

    def __init__(self,
                 iedriver_path: str,
                 username="",
                 password="",
                 grid_password=""):
        """Creates a webdriver with VASS authentication completed.
    
        Creates an instance of selenium.webdriver.Ie and authenticates to VASS.
        
        Args:
            iedriver_path: The path to geckodriver.exe
            username: The username to login with
            password: The password to login with
            grid_password: The grid password to login with. A sequence of
                tuples, each tuple being the grid coordinate of the next
                password character. Must be given in top-> bottom, left->
                right order.

        Returns:
            An instance of selenium.webdriver.ie with authentication to
            VASS completed.
        """
        ieCapabilities = DesiredCapabilities.INTERNETEXPLORER.copy()
        ieCapabilities["nativeEvents"] = False
        ieCapabilities["unexpectedAlertBehaviour"] = "accept"
        ieCapabilities["ignoreProtectedModeSettings"] = True
        ieCapabilities["disable-popup-blocking"] = True
        ieCapabilities["enablePersistentHover"] = True
        ieCapabilities["ignoreZoomSetting"] = True

        super().__init__(executable_path=iedriver_path,
                         desired_capabilities=ieCapabilities)

        self.launch_window = self.current_window_handle
        # login to VASS
        self.get("https://www.vass.vic.edu.au/login/")

        time.sleep(2)
        login_link = WebDriverWait(self, 20).until(
            EC.element_to_be_clickable((By.NAME, "boslogin")))
        click_with_retry(login_link, lambda: find_window(self, "Login To VASS"))
        time.sleep(1)
        handle = find_window(self, "Login To VASS")
        self.switch_to.window(handle)
        self.main_window = self.current_window_handle

        # username/password auth
        self.find_element_by_name("username").send_keys(username)
        self.find_element_by_name("password").send_keys(password)
        self.find_element_by_xpath("//input[contains(@name, 'Login')]").click()
        # password grid auth
        WebDriverWait(self, 10).until(
            EC.presence_of_element_located((By.NAME, 'PASSCODEGRID')))
        pattern = r'type=input value=(?P<value>[A-Za-z0-9!@#\$%\^&\*~\+=]) name=PASSCODEGRID MaxCol="8" MaxList="64" PassListLength="6" QuadrantNum="[0-9]" ColumnNum="(?P<col>[0-9])" RowNum="(?P<row>[0-9])"'
        ms = re.findall(pattern, self.page_source)
        grid_values = {}
        for m in ms:
            grid_values[(m[1], m[2])] = m[0]
        grid_password_characters = "".join(
            [grid_values[i] for i in grid_password])
        self.find_element_by_xpath("//input[contains(@name, 'PassCode')]"
                                  ).send_keys(grid_password_characters)
        self.find_element_by_xpath(
            "//input[contains(@name, 'AcceptButton')]").click()
        WebDriverWait(self, 20).until(EC.title_contains("VASS - "))
        pattern = "VASS - (?P<school>[A-Za-z ]+) - Year (?P<year>[0-9]{4})"
        m = re.match(pattern, self.title)
        if m:
            self.school = m.group('school')
            self.year = m.group('year')

    def execute_click(self, element):
        self.set_script_timeout(1)
        try:
            self.execute_script("arguments[0].click()", element)
        except TimeoutException:
            pass
        self.set_script_timeout(30)  #default

    def change_year(self, year: str) -> None:
        """Changes the year in VASS.
        
        Args:
            year: The year to change to.
        """
        self.switch_to.default_content()
        # ignore tempramental menu and just inject the menu click
        WebDriverWait(self, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "main")))
        current_handles = self.window_handles
        menu_item = self.find_element_by_xpath(
            "//*[contains(text(),'Change Year')]")
        self.execute_click(menu_item)
        time.sleep(0.5)
        WebDriverWait(self, 20).until(EC.new_window_is_opened(current_handles))
        for handle in self.window_handles:
            self.switch_to.window(handle)
            if self.title == "Change Code/Year":
                break
        WebDriverWait(self, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "VASSFrame")))
        #self.switch_to.frame('VASSFrame')
        year_field = self.find_element_by_name("Year")
        year_field.send_keys(year)
        continue_button = self.find_element_by_xpath("//input[@type='submit']")
        continue_button.click()
        time.sleep(1)
        self.switch_to.window(self.main_window)
        self.year = year

    def external_results(self, file_name):
        """Saves the student external results (study scores) to a csv.
        
        Args:
            file_name: The file name to save the data as.    
        """
        external_results_url = "https://www.vass.vic.edu.au/results/reports/GradedAssessmentResultsByClass/GAResultsReport.vass?StudySequenceCode=ALL&ClassCode=&Semester=ALL&ReportOrder=Unit&exportReport=Y"
        s = requests.session()
        # copy cookies from selenium session
        for cookie in self.get_cookies():
            c = {cookie['name']: cookie['value']}
            s.cookies.update(c)
        # request student details file
        r = s.get(external_results_url)

        names = [
            "Unit Code", "Unit Name", "Class Code", "Semester", "Teacher Code",
            "Teacher Name", "Year Level", "Form Group", "Student Number",
            "Student Name", "Gender", "Unit 3 Result", "Unit 4 Result",
            "GA 1 Result", "GA 2 Result", "GA 3 Result", "Study Score", "Blank"
        ]
        df = pd.read_csv(StringIO(r.content.decode('utf-8')),
                         sep="|",
                         names=names,
                         skiprows=1)
        df.to_csv(file_name, index=False)

    def school_program_summary(self, file_name: str, report: str = "vce"):
        """Saves the school program summary to a csv file.
        
        Args:
            file_name: The file name to save the data to.
            report: "vce", "vet" or "vcal"
        """
        base_url = "https://www.vass.vic.edu.au/schoolprog/reports/SchoolProgramSummary/SchoolProgramSummary.vass?TeacherNum=&UnitLevel=0&Semester=0&ReportSelection="
        url = base_url + report
        s = requests.session()
        # copy cookies from selenium session
        for cookie in self.get_cookies():
            c = {cookie['name']: cookie['value']}
            s.cookies.update(c)
        # request student details file
        r = s.get(url)
        names = [
            "Unit Code", "Unit Name", "Teacher Code", "Teacher Name",
            "Semester", "Class Code", "Class Size", "Time Block"
        ]
        df = pd.read_csv(StringIO(r.content.decode('utf-8')),
                         sep="|",
                         names=names,
                         skiprows=1,
                         skipfooter=1,
                         engine='python')
        df.fillna("", inplace=True)
        df.to_csv(file_name, index=False)

    def personal_details_summary(self, file_name: str):
        """Saves the student personal details summary to a csv file.
        
        Args:
            file_name: The file name to save the data to.
        """
        personal_details_url = "https://www.vass.vic.edu.au/student/reports/StudentPersonalDetailsSummary/PersonalDetailsSummary.vass?yearLevel=ALL&formGroup=&course=ALL&reportType=1&includeAddress=N&reportOrder=yrLevel"
        s = requests.session()
        # copy cookies from selenium session
        for cookie in self.get_cookies():
            c = {cookie['name']: cookie['value']}
            s.cookies.update(c)
        # request student details file
        r = s.get(personal_details_url)
        names = [
            "Year Level", "Form Group", "Student Number", "Family Name",
            "First Name", "Second Name", "External ID", "Gender",
            "Phone Number", "Date of Birth", "Course"
        ]
        df = pd.read_csv(StringIO(r.content.decode('utf-8')),
                         sep="|",
                         names=names,
                         skiprows=1,
                         skipfooter=1,
                         engine='python')
        df.fillna("", inplace=True)
        df.to_csv(file_name, index=False)

    # TODO: See if data can be downloaded directly from https://www.vass.vic.edu.au/results/reports/GATResultsSummary/GATResultsSummary_Display.cfm?&yr=" + year_level + "&form=" + form_group + "&myIndex=1&myTotal=1"
    def gat_summary(self, file_name: str) -> None:
        """Extracts student GAT results and saves them to a csv.
        
        Args:
            file_name: The file name for the csv to save the data to.
        """
        self.switch_to.default_content()
        WebDriverWait(self, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "main")))
        menu_item = WebDriverWait(self, 10).until(
            EC.presence_of_element_located((By.ID, "item7_3_1"))) # GAT Summary
        self.execute_click(menu_item)
        current_handles = self.window_handles
        # run report
        try:
            button = WebDriverWait(self, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                    "//input[(@name='btnRunReport') and (@type='submit')]")))
        except TimeoutException:
            self.switch_to.default_content()
            WebDriverWait(self, 10).until(
                EC.frame_to_be_available_and_switch_to_it((By.NAME, "main")))
            menu_item = self.find_element_by_id("item7_3_1")
            self.execute_click(menu_item)
            button = WebDriverWait(self, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                    "//input[(@name='btnRunReport') and (@type='submit')]")))
        self.execute_click(button)
        time.sleep(0.5)
        WebDriverWait(self, 20).until(EC.new_window_is_opened(current_handles))
        gat_window = find_window(
            self, f"GAT Results Summary for {self.school} - {self.year}")
        self.switch_to.window(gat_window)
        students = []
        while (True):
            self.switch_to.frame('VASSFrame')
            report_data = WebDriverWait(self, 30).until(
                EC.presence_of_element_located((By.ID, 'reportData')))
            data = report_data.get_attribute('innerHTML')
            try:
                root = ET.fromstring(data.strip())
            except ET.ParseError:
                time.sleep(2) # try giving page more time to load
                report_data = WebDriverWait(self, 30).until(
                    EC.presence_of_element_located((By.ID, 'reportData')))
                data = report_data.get_attribute('innerHTML')
                root = ET.fromstring(data.strip())
            for child in root.iter('student'):
                students.append(child.attrib)
            self.switch_to.parent_frame()
            self.switch_to.frame('VASSTop')
            try:
                self.find_element_by_id("idNext").click()  # next subject
            except ElementNotInteractableException:
                break
            self.switch_to.parent_frame()
            time.sleep(0.1)
        self.switch_to.parent_frame()
        self.switch_to.frame('VASSTop')
        self.find_element_by_id("idClose").click()
        self.switch_to.window(self.main_window)
        df = pd.DataFrame(students)
        df.rename(columns={
            "CandNum": "Student Number",
            "name": "Student Name"
        },
                  inplace=True)
        df.to_csv(file_name, index=False)

    # TODO: See if data can be downloaded  directly from https://www.vass.vic.edu.au/common/VASSExtract.cfm?Filename=" + unit_code + ga_code
    def school_scores(self, file_name: str) -> None:
        """Extracts school score data for all GAs and saves to a csv.
        
        Args:
            file_name: The filename to save the data to.
        """
        # open ranked school scores report page
        # TODO: possibly can open this directly with a javascript click instead of driver click
        self.switch_to.default_content()
        WebDriverWait(self, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "main")))
        menu_item = WebDriverWait(self, 30).until(
            EC.presence_of_element_located((By.ID, 'item7_3_3_2')))
        #menu_item = self.find_element_by_id(
        #    "item7_3_3_2")  # Subject ranked summaries
        self.execute_click(menu_item)
        # scrape all of the school scores
        school_scores = []
        cycle_names = [
            "5 - U3 SAT Results", "6 - Unit 3 School-assessed Coursework",
            "8 - Unit 4 SAT and SAC"
        ]
        for cycle in cycle_names:
            self.switch_to.default_content()
            self.switch_to.frame('main')
            self.find_element_by_xpath(
                f"//select[@name='CycleNum']/option[text()='{cycle}']").click()
            button = self.find_element_by_xpath(
                "//input[@value='Run Ranked School Scores Report']")
            current_handles = self.window_handles
            self.execute_click(button)
            WebDriverWait(self,
                          20).until(EC.new_window_is_opened(current_handles))
            handle = find_window(
                self,
                f"Ranked School Scores Report for {self.school} - {self.year}")
            self.switch_to.window(handle)
            while (True):
                self.switch_to.frame("VASSFrame")
                for i in range(10):
                    try:
                        data = WebDriverWait(self, 30).until(
                            EC.presence_of_element_located(
                                (By.ID,
                                 'reportData'))).get_attribute('innerHTML')
                        root = ET.fromstring(data.strip())
                        max_score = root.get("MaxScore")
                        siar = root.get("SIAR")
                        siar_max_score = root.get("SIARMaxScore")
                        break
                    except ET.ParseError:
                        time.sleep(1)
                params = {
                    'Max Score': max_score,
                    "SIAR": siar,
                    "SIAR Max Score": siar_max_score
                }
                for child in root.iter('param'):
                    params[child.attrib['name']] = child.attrib['value']
                del params['Students Assessed Elsewhere']
                for child in root.iter('student'):
                    school_scores.append({**child.attrib, **params})
                self.switch_to.parent_frame()
                self.switch_to.frame('VASSTop')
                try:
                    self.find_element_by_id("idNext").click()  # next subject
                except ElementNotInteractableException:
                    break
                self.switch_to.parent_frame()
            self.switch_to.parent_frame()
            self.switch_to.frame('VASSTop')
            self.find_element_by_id("idClose").click()
            self.switch_to.window(self.main_window)
        df = pd.DataFrame(school_scores)
        subject_names = {}
        unit_names = df["Unit"]
        pattern = "(?P<code>[A-Z]{2}[0-9]{2})[34] - (?P<name>[A-Z :\(\)]+) [34]"
        for unit in unit_names:
            m = re.match(pattern, unit)
            if m:
                subject_names[unit] = m.group('name')
        df["Unit Code"] = df["Unit"].str[:4]
        df["Unit Name"] = df["Unit"].map(subject_names)
        #df.drop(["Unit"], inplace=True)
        df.drop_duplicates(inplace=True)
        df.rename(columns={
            "CandNum": "Student Number",
            "name": "Student Name",
            "focus_area": "Focus Area",
            "class_cd": "Class",
            "result": "Result"
        },
                  inplace=True)
        df.to_csv(file_name, index=False)

    def predicted_scores(self, file_name: str):
        """Exports student achieved and predicted scores from Report 17.
        
        Uses the currently selected year in VASS even though the Report 17 UI
        allows for year selection.

        Args:
            file_name: The csv to save to.
        """
        self.switch_to.default_content()
        WebDriverWait(self, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "main")))
        menu_item = WebDriverWait(self, 10).until(
            EC.presence_of_element_located((By.ID, "item2_6_1")))
        self.execute_click(menu_item)
        time.sleep(0.5)
        button = WebDriverWait(self, 10).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "//input[@value='Run VCE Data Service Reporting System']")))
        current_handles = self.window_handles
        self.execute_click(button)
        WebDriverWait(self, 20).until(EC.new_window_is_opened(current_handles))
        handle = find_window(
            self, f"VCE Data System Reporting for {self.school} - {self.year}")
        self.switch_to.window(handle)
        # open report 17
        self.switch_to.frame('VASSTop')
        report17 = self.find_element_by_id('btnReport17')
        self.execute_click(report17)
        # select year
        year_select_element = WebDriverWait(self, 5).until(
            EC.presence_of_element_located(
                (By.ID, 'mainHolder_Report17_ddlYear')))
        select = Select(year_select_element)
        select.select_by_visible_text(self.year)
        # select all subjects, trying doing this with action chains later, might be faster
        time.sleep(0.5)
        subject_select_element = WebDriverWait(self, 5).until(
            EC.presence_of_element_located(
                (By.ID, 'mainHolder_Report17_lstSubjects')))
        select = Select(subject_select_element)
        n_subjects = len(select.options)
        for i in range(n_subjects):
            select_element = WebDriverWait(self, 5).until(
                EC.presence_of_element_located(
                    (By.ID, 'mainHolder_Report17_lstSubjects')))
            select = Select(select_element)
            select.select_by_index(i)
            time.sleep(0.5)
        button = self.find_element_by_id('mainHolder_btnReport')
        self.execute_click(button)
        time.sleep(1)
        results = []
        while True:
            WebDriverWait(self, 10).until(
                EC.presence_of_element_located((By.ID, 'mainHolder_pnlReport')))
            page_source = self.page_source
            # get subject
            pattern = r'>(?P<subject>[A-Za-z :\(\)]+):&nbsp;&nbsp;Student Results by Study'
            m = re.search(pattern, page_source)
            subject = m.group('subject')
            # get student results
            pattern = '<TR>\r\n<TD align=left style="BORDER-TOP: black 1px solid; BORDER-RIGHT: black 1px solid; WIDTH: 150px; BORDER-BOTTOM: black 1px solid; FONT-WEIGHT: normal; BORDER-LEFT: black 1px solid">&nbsp;(?P<surname>[A-Za-z-\']+)</TD>\r\n<TD align=left style="BORDER-TOP: black 1px solid; BORDER-RIGHT: black 1px solid; WIDTH: 150px; BORDER-BOTTOM: black 1px solid; FONT-WEIGHT: normal; BORDER-LEFT: black 1px solid">&nbsp;(?P<firstname>[A-Za-z- ]+)</TD>\r\n<TD align=center style="BORDER-TOP: black 1px solid; BORDER-RIGHT: black 1px solid; WIDTH: 100px; BORDER-BOTTOM: black 1px solid; FONT-WEIGHT: normal; BORDER-LEFT: black 1px solid">(?P<yearlevel>[0-9]+)</TD>\r\n<TD align=center style="BORDER-TOP: black 1px solid; BORDER-RIGHT: black 1px solid; WIDTH: 100px; BORDER-BOTTOM: black 1px solid; FONT-WEIGHT: normal; BORDER-LEFT: black 1px solid">(?P<classgroup>[A-Za-z0-9]+)</TD>\r\n<TD align=center style="FONT-SIZE: 8pt; BORDER-TOP: black 1px solid; BORDER-RIGHT: black 1px solid; WIDTH: 100px; BORDER-BOTTOM: black 1px solid; FONT-WEIGHT: normal; BORDER-LEFT: black 1px solid">(?P<achieved>[0-9.]+)</TD>\r\n<TD align=center style="FONT-SIZE: 8pt; BORDER-TOP: black 1px solid; BORDER-RIGHT: black 1px solid; WIDTH: 100px; BORDER-BOTTOM: black 1px solid; FONT-WEIGHT: normal; BORDER-LEFT: black 1px solid">(?P<predicted>[0-9.]+)</TD></TR>'
            ms = re.findall(pattern, page_source)
            new_results = [{
                'Year': self.year,
                'Subject': subject,
                'Surname': m[0],
                'FirstName': m[1],
                'YearLevel': m[2],
                'ClassGroup': m[3],
                'Achieved': m[4],
                'Predicted': m[5]
            } for m in ms]
            results += new_results
            # go to next subject
            next_button = self.find_element_by_name(
                'ctl00$mainHolder$ReportHeader1$btnNext')
            if next_button.get_attribute('disabled') == 'true':
                break
            self.execute_click(next_button)
            time.sleep(1)
        close_button = self.find_element_by_id(
            'mainHolder_ReportHeader1_btnClose')
        self.execute_click(close_button)
        self.close()
        self.switch_to.window(self.main_window)
        df = pd.DataFrame.from_records(results)
        df.to_csv(file_name, index=False)
