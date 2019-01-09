"""
Tests Figures multisite/standalone site support handlers

The multisite tests require Appsembler's fork of edx-organizations installed

The test classes in this module handle the following conditions
* Standalone mode (run regardless if organizations supports sites)
* Multisite mode when organizations supports sites
* Multisite mode when organizations does not support sites

Current structure
=================

We're structuring the test classes around the data setup required so that we're
minimizing extra data set up:

* Single test class for standalone mode
* Multiple test classes for multisite mode

TODOs: Create base test class for the multisite setup (and teardown if needed)
or restructure into fixtures and standalone test functions, depending on how
figures.sites evolves
"""

import mock
import pytest

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site

import organizations

from openedx.core.djangoapps.content.course_overviews.models import (
    CourseOverview,
)

import figures.settings
import figures.sites

from tests.factories import (
    CourseEnrollmentFactory,
    CourseOverviewFactory,
    OrganizationFactory,
    OrganizationCourseFactory,
    SiteFactory,
    UserFactory,
    # Appsembler specific
    # UserOrganizationMappingFactory,
)
from tests.helpers import organizations_support_sites


if organizations_support_sites():
    from tests.factories import UserOrganizationMappingFactory


@pytest.mark.django_db
class TestHandlersForStandaloneMode(object):
    """
    Tests figures.sites site handling functions in standalone site mode
    These tests should pass regardless of whether or not and if so how
    organizations supports organization-site mapping
    """

    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.default_site = Site.objects.get()
        self.env_tokens = {'IS_FIGURES_MULTISITE': False}
        self.site = Site.objects.first()
        assert Site.objects.count() == 1
        assert not figures.settings.is_multisite()

    def test_get_site_for_course(self):
        """

        """
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            co = CourseOverviewFactory()
            site = figures.sites.get_site_for_course(str(co.id))
            assert site == Site.objects.first()

    @pytest.mark.parametrize('course_count', [0, 1, 2])
    def test_get_course_keys_for_site(self, course_count):
        sites = Site.objects.all()
        assert sites.count() == 1
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            course_overviews = [CourseOverviewFactory() for i in range(course_count)]
            course_keys = figures.sites.get_course_keys_for_site(sites[0])
            expected_ids = [str(co.id) for co in course_overviews]
            assert set([str(key) for key in course_keys]) == set(expected_ids)

    def test_get_courses_for_site(self):
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            courses = figures.sites.get_courses_for_site(self.site)
            assert set(courses) == set(CourseOverview.objects.all())

    def test_get_user_ids_for_site(self):
        expected_users = [UserFactory() for i in range(3)]
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            user_ids = figures.sites.get_user_ids_for_site(self.site)
            assert set(user_ids) == set([user.id for user in expected_users])

    def test_get_users_for_site(self):
        expected_users = [UserFactory() for i in range(3)]
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            users = figures.sites.get_users_for_site(self.site)
            assert set([user.id for user in users]) == set(
                       [user.id for user in expected_users])

    def test_get_course_enrollments_for_site(self):
        expected_ce = [CourseEnrollmentFactory() for i in range(3)]
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            course_enrollments = figures.sites.get_course_enrollments_for_site(self.site)
            assert set([ce.id for ce in course_enrollments]) == set(
                       [ce.id for ce in expected_ce])


@pytest.mark.skipif(not organizations_support_sites(),
                    reason='Organizations support sites')
@pytest.mark.django_db
class TestHandlersForMultisiteMode(object):
    """
    Tests figures.sites site handling functions in multisite mode

    Assumptions:
    * We're using Appsembler's fork of `edx-organizations` for the multisite
      tests

    """
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.site = SiteFactory(domain='foo.test')
        self.organization = OrganizationFactory(sites=[self.site])
        assert Site.objects.count() == 2
        self.env_tokens = {'IS_FIGURES_MULTISITE': True}

    def test_get_site_for_courses(self):
        """
        Can we get the site for a given course?

        We shouldn't care what the other site is. For reference, it is the
        default site with 'example.com' for both the domain and name fields
        """
        # We want to move the patch to the class level if possible
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            assert figures.settings.is_multisite()
            co = CourseOverviewFactory()
            OrganizationCourseFactory(organization=self.organization,
                                      course_id=str(co.id))
            site = figures.sites.get_site_for_course(str(co.id))
            assert site == self.site

    def test_get_site_for_course_not_in_site(self):
        """
        We create a course but don't add the course to OrganizationCourse
        We expect that a site cannot be found
        """
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            assert figures.settings.is_multisite()
            co = CourseOverviewFactory()
            site = figures.sites.get_site_for_course(str(co.id))
            assert not site

    @pytest.mark.parametrize('course_id', ['', None])
    def test_get_site_for_non_existing_course(self, course_id):
        """
        We expect no site returned for None for the course
        """
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            assert figures.settings.is_multisite()
            site = figures.sites.get_site_for_course(course_id)
            assert not site

    @pytest.mark.parametrize('course_count', [0, 1, 2])
    def test_get_course_keys_for_site(self, course_count):
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            assert figures.settings.is_multisite()
            course_overviews = [CourseOverviewFactory() for i in range(course_count)]
            for co in course_overviews:
                OrganizationCourseFactory(organization=self.organization,
                                          course_id=str(co.id))
            course_keys = figures.sites.get_course_keys_for_site(self.site)
            expected_ids = [str(co.id) for co in course_overviews]
            assert set([str(key) for key in course_keys]) == set(expected_ids)

    @pytest.mark.parametrize('course_count', [0, 1, 2])
    def test_get_courses_for_site(self, course_count):
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            assert figures.settings.is_multisite()
            course_overviews = [CourseOverviewFactory() for i in range(course_count)]
            for co in course_overviews:
                OrganizationCourseFactory(organization=self.organization,
                                          course_id=str(co.id))
            courses = figures.sites.get_courses_for_site(self.site)
            expected_ids = [str(co.id) for co in course_overviews]
            assert set([str(co.id) for co in courses]) == set(expected_ids)

    @pytest.mark.parametrize('ce_count', [0, 1, 2])
    def test_get_course_enrollments_for_site(self, ce_count):
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            assert figures.settings.is_multisite()
            course_overview = CourseOverviewFactory()
            OrganizationCourseFactory(organization=self.organization,
                                      course_id=str(course_overview.id))
            expected_ce = [CourseEnrollmentFactory(
                course_id=course_overview.id) for i in range(ce_count)]
            course_enrollments = figures.sites.get_course_enrollments_for_site(self.site)
            assert set([ce.id for ce in course_enrollments]) == set(
                       [ce.id for ce in expected_ce])


@pytest.mark.skipif(not organizations_support_sites(),
                    reason='Organizations support sites')
@pytest.mark.django_db
class TestUserHandlersForMultisiteMode(object):
    """
    Tests figures.sites site handling functions in multisite mode

    Test does not yet provide multiple sites/orgs to test leakiness

    Assumptions:
    * We're using Appsembler's fork of `edx-organizations` for the multisite
      tests

    """
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.site = SiteFactory(domain='foo.test')
        self.organization = OrganizationFactory(
            sites=[self.site],
        )
        assert get_user_model().objects.count() == 0
        self.users = [UserFactory() for i in range(3)]
        for user in self.users:
            UserOrganizationMappingFactory(user=user,
                                           organization=self.organization)
        assert Site.objects.count() == 2
        self.env_tokens = {'IS_FIGURES_MULTISITE': True}

    def test_get_user_ids_for_site(self):
        expected_users = self.users
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            user_ids = figures.sites.get_user_ids_for_site(self.site)
            assert set(user_ids) == set([user.id for user in expected_users])

    def test_get_users_for_site(self):
        expected_users = self.users
        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            users = figures.sites.get_users_for_site(self.site)
            assert set([user.id for user in users]) == set(
                       [user.id for user in expected_users])


@pytest.mark.skipif(organizations_support_sites(),
                    reason='Organizations package does not support sites')
@pytest.mark.django_db
class TestOrganizationsLacksSiteSupport(object):
    """
    This class tests how the figures.sites module handles multisite mode when
    organizations models do not associate organizations with sites

    TODO: Improve test coverage
    """
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.site = SiteFactory(domain='foo.test')
        assert Site.objects.count() == 2
        self.env_tokens = {'IS_FIGURES_MULTISITE': True}

    def test_create_organiztion_with_site(self):
        """
        Make sure that we cannot associate an organization with a site

        Another way to check is if organizations.models.Organization has the
        'sites' field via `hasattr`
        """
        with pytest.raises(TypeError):
            OrganizationFactory(sites=[self.site])

    def test_org_course_missing_sites_field(self):

        with mock.patch('figures.settings.env_tokens', self.env_tokens):
            # orgs = organizations.models.Organization.objects.all()
            # assert orgs
            # msg = 'Not supposed to have "sites" attribute'
            assert not hasattr(
                organizations.models.Organization, 'sites'), msg
