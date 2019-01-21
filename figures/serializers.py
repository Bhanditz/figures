"""Serializers used in Figures

Outstanding issues
------------------

For learner details, dates are not stored for when sections and/or subsections
are completed

For course details, same issue for average progress, average completion time

Other history sections can get data by iterating over start and end dates as
time series data. However, this can generate many queries. Therefore, we are
looking at adding additional Figures models to capture:
* aggregate data
* data that cannot be queries as part of a time series
* data that are time consuming, like dynamic grade retrieval

"""

import datetime

from django.contrib.auth import get_user_model
from django_countries import Countries
from rest_framework import serializers

from openedx.core.djangoapps.content.course_overviews.models import (
    CourseOverview,
)
from openedx.core.djangoapps.user_api.accounts.serializers import (
    AccountLegacyProfileSerializer,
)

from certificates.models import GeneratedCertificate
from student.models import CourseAccessRole, CourseEnrollment

from figures.helpers import as_course_key
from figures.metrics import (
    get_course_enrolled_users_for_time_period,
    get_course_average_progress_for_time_period,
    get_course_average_days_to_complete_for_time_period,
    get_course_num_learners_completed_for_time_period,
    get_monthly_history_metric,
    )
from figures.models import (
    CourseDailyMetrics,
    SiteDailyMetrics,
    LearnerCourseGradeMetrics,
    PipelineError,
    )
from figures.pipeline.logger import log_error
import figures.sites


# Temporarily hardcoding here
# TODO: put into figures.settings
HISTORY_MONTHS_BACK = 6


#
# Serializer Field classes
#


class SerializeableCountryField(serializers.ChoiceField):
    """
    This class addresses an issue with django_countries that does not serialize
    blank country values. See here:

        https://github.com/SmileyChris/django-countries/issues/106
    """
    def __init__(self, **kwargs):
        super(SerializeableCountryField, self).__init__(choices=Countries(), **kwargs)

    def to_representation(self, value):
        if value in ('', None):
            # normally here it would return value.
            # which is Country(u'') and not serialiable
            # See the issue linked in the class docstring
            return ''

        return super(SerializeableCountryField, self).to_representation(value)


#
# Summary serializers for listing
#


class CourseIndexSerializer(serializers.Serializer):
    """Provides a limited set of course overview information

    The full set returned by the edx-platform built-in course api can be found
    in this class:

        lms.djangoapps.course_api.serializers.CourseSerializer
    """

    id = serializers.CharField()
    name = serializers.CharField(source='display_name_with_default_escaped')
    org = serializers.CharField(source='display_org_with_default')
    number = serializers.CharField(source='display_number_with_default')


class UserIndexSerializer(serializers.Serializer):
    """Provides a limited set of user information for summary display
    """
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    fullname = serializers.CharField(
        source='profile.name', default=None, read_only=True)


#
# Serializers for edx-platform models
#


class CourseOverviewSerializer(serializers.ModelSerializer):

    class Meta:
        model = CourseOverview
        fields = (
            'id', 'display_name', 'org',
        )


class CourseEnrollmentSerializer(serializers.ModelSerializer):
    """Provides CourseOverview model based serialization

    """
    course = CourseOverviewSerializer(read_only=True)
    user = UserIndexSerializer(read_only=True)

    class Meta:
        model = CourseEnrollment
        editable = False


#
# Figures model serializers
#


class CourseDailyMetricsSerializer(serializers.ModelSerializer):
    """Provides summary data about a specific course
    """
    average_progress = serializers.DecimalField(max_digits=2, decimal_places=2)

    class Meta:
        model = CourseDailyMetrics


class SiteDailyMetricsSerializer(serializers.ModelSerializer):
    """Proviedes summary data about the LMS site
    """

    class Meta:
        model = SiteDailyMetrics


#
# Serializers for serving the front end views
#


class CourseAccessRoleForGCDSerializer(serializers.ModelSerializer):
    """Serializer to return course staff data for GeneralCourseData
    """

    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    fullname = serializers.CharField(
        source='user.profile.name', default=None, read_only=True)
    role = serializers.CharField(read_only=True)

    class Meta:
        model = CourseAccessRole
        fields = ['user_id', 'username', 'fullname', 'role']


class GeneralCourseDataSerializer(serializers.Serializer):
    """

    Returns data in the format::

        [
            {
                "course_id": "A101+SomethingSomething",
                "course_name": "This is the course name",
                "course_code": "A101",
                "course_mode": "Something",
                "org": "MyOrganization",
                "start_date": "2017-07-15T16:59:51.740702Z", // can be empty
                "end_date": "2017-07-15T16:59:51.740702Z", // can be empty
                "self_paced": false,
                "staff": [
                    {
                        "username": "matej",
                        "fullname": "Matej Grozdanovic",
                        "user_id": 123,
                        "role": "instructor"
                    },
                    {
                        "username": "bubba",
                        "fullname": "Bubba Brown",
                        "user_id": 42,
                        "role": "staff"
                    }
                ],
                "metrics": {
                    "learners_enrolled": 123,
                    "average_progress": 0.39, // percentage
                    "average_completion_time": "some_time_in_standardised_format",
                    "users_completed": 493, // total number of users that have
                                            // completed the course since the
                                            // course was created
                }
            },
            ...
        ]

    """
    course_id = serializers.CharField(source='id', read_only=True)
    course_name = serializers.CharField(
        source='display_name_with_default_escaped', read_only=True)
    course_code = serializers.CharField(
        source='display_number_with_default', read_only=True)
    org = serializers.CharField(
        source='display_org_with_default', read_only=True)
    start_date = serializers.DateTimeField(
        source='enrollment_start', read_only=True, default=None)
    end_date = serializers.DateTimeField(
        source='enrollment_end', read_only=True, default=None)
    self_paced = serializers.BooleanField(read_only=True)

    staff = serializers.SerializerMethodField()

    metrics = serializers.SerializerMethodField()

    def get_staff(self, obj):
        qs = CourseAccessRole.objects.filter(course_id=obj.id)
        if qs:
            return [CourseAccessRoleForGCDSerializer(data).data for data in qs]
        else:
            return []

    def get_metrics(self, obj):
        qs = CourseDailyMetrics.objects.filter(course_id=str(obj.id))
        if qs:
            return CourseDailyMetricsSerializer(qs.latest('date_for')).data
        else:
            return []


def get_course_history_metric(site, course_id, func, date_for, months_back):
    """Retieves current_month and history metric data for a course and time
    period

    This is a convenience function to reduce duplicate code

    :param course_id: The course identifier for the course we want data
    :param func: The metric function to retrieve a metric for the specified
    course and date range
    :param date_for: The date to determine the current month
    :param months_back: How many months back to retrieve data
    :returns: a dict with the current month metric and list of metrics for
    previous months
    """
    # wrapper_func = lambda start_date, end_date: func(
    #         start_date=start_date,
    #         end_date=end_date,
    #         course_id=course_id)

    # def wrapper_func(start_date, end_date):
    #         start_date=start_date,
    #         end_date=end_date,
    #         course_id=course_id

    return get_monthly_history_metric(
        func=lambda site, start_date, end_date: func(
            site=site,
            start_date=start_date,
            end_date=end_date,
            # site=site,
            course_id=course_id),
        site=site,
        date_for=date_for,
        months_back=months_back,
        )


class CourseDetailsSerializer(serializers.ModelSerializer):
    """

    Initial implementation uses serializer emthods to retrieve some data

    Need to ask edX team why CourseEnrollment doesn't have a foreign key
    relationship to CourseOverview
    """
    course_id = serializers.CharField(source='id', read_only=True)
    course_name = serializers.CharField(
        source='display_name_with_default_escaped', read_only=True)
    course_code = serializers.CharField(
        source='display_number_with_default', read_only=True)
    org = serializers.CharField(
        source='display_org_with_default', read_only=True)
    start_date = serializers.DateTimeField(
        source='enrollment_start', read_only=True, default=None)
    end_date = serializers.DateTimeField(
        source='enrollment_end', read_only=True, default=None)
    self_paced = serializers.BooleanField(read_only=True)

    staff = serializers.SerializerMethodField()

    learners_enrolled = serializers.SerializerMethodField()
    average_progress = serializers.SerializerMethodField()
    average_days_to_complete = serializers.SerializerMethodField()
    users_completed = serializers.SerializerMethodField()

    # TODO: Consider if we want to add a hyperlink field to the learner details endpoint

    class Meta:
        model = CourseOverview
        fields = ['course_id', 'course_name', 'course_code', 'org', 'start_date',
                  'end_date', 'self_paced', 'staff', 'learners_enrolled',
                  'average_progress', 'average_days_to_complete', 'users_completed', ]
        read_only_fields = fields

    def to_representation(self, instance):
        """
        This is a hack to get the site for this course
        We do this because the figures.metrics calls we are making require the
        site object as a parameter
        """
        self.site = figures.sites.get_site_for_course(instance)
        ret = super(CourseDetailsSerializer, self).to_representation(instance)
        return ret

    def get_staff(self, course_overview):
        qs = CourseAccessRole.objects.filter(course_id=course_overview.id)
        if qs:
            return [CourseAccessRoleForGCDSerializer(data).data for data in qs]
        else:
            return []

    def get_learners_enrolled(self, course_overview):
        """
        Would be nice to have the course_enrollment and course_overview models
        linked
        """
        return get_course_history_metric(
            site=self.site,
            course_id=course_overview.id,
            func=get_course_enrolled_users_for_time_period,
            date_for=datetime.datetime.utcnow(),
            months_back=HISTORY_MONTHS_BACK,
            )

    def get_average_progress(self, course_overview):
        """
        """
        return get_course_history_metric(
            site=self.site,
            course_id=course_overview.id,
            func=get_course_average_progress_for_time_period,
            date_for=datetime.datetime.utcnow(),
            months_back=HISTORY_MONTHS_BACK,
            )

    def get_average_days_to_complete(self, course_overview):
        """
        """
        return get_course_history_metric(
            site=self.site,
            course_id=course_overview.id,
            func=get_course_average_days_to_complete_for_time_period,
            date_for=datetime.datetime.utcnow(),
            months_back=HISTORY_MONTHS_BACK,
            )

    def get_users_completed(self, course_overview):
        """
        """
        return get_course_history_metric(
            site=self.site,
            course_id=course_overview.id,
            func=get_course_num_learners_completed_for_time_period,
            date_for=datetime.datetime.utcnow(),
            months_back=HISTORY_MONTHS_BACK,
            )


class GeneralSiteMetricsSerializer(serializers.Serializer):
    """
    Because of the way figures.metrics.get_monthly_site_metrics *currently*
    works, we don't need a serializer. But we will when we refactor the metrics
    module and add the site monthly metrics model
    """
    monthly_active_users = serializers.SerializerMethodField()
    total_site_users = serializers.SerializerMethodField()
    total_site_courses = serializers.SerializerMethodField()
    total_course_enrollments = serializers.SerializerMethodField()
    total_course_completions = serializers.SerializerMethodField()

    def get_monthly_active_users(self, obj):
        return dict(
        )

    def get_total_site_users(self, obj):
        return dict(
        )

    def get_total_site_courses(self, obj):
        return dict(
        )

    def get_total_course_enrollments(self, obj):
        return dict(
        )

    def get_total_course_completions(self, obj):
        return dict(
        )


# The purpose of this serialzer is to provide summary info for a learner
# so we're
class GeneralUserDataSerializer(serializers.Serializer):
    """

    Example from API docs:
     {
        "username": "maxi",
        "country": "UY",
        "is_active": true,
        "year_of_birth": 1985,
        "level_of_education": "b",
        "gender": "m",
        "date_joined": "2018-05-06T14:01:58Z",
        "language_proficiencies": [],
        "courses": [
          {
            "course_name": "Something",
            "course_id": "A193+2016Q4+something",
          }
          ...
        ]
      },

    Changes from spec:
    courses list:
    - uses 'id' instead of 'course_id'
    - includes additional fields, org and number, as we are reusing the
    CourseIndexSerializer
    """

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    fullname = serializers.CharField(
        source='profile.name', default=None, read_only=True)

    country = SerializeableCountryField(
        source='profile.country',
        required=False,
        read_only=True,
        allow_blank=True)
    is_active = serializers.BooleanField(read_only=True)
    year_of_birth = serializers.IntegerField(
        source='profile.year_of_birth', read_only=True)
    gender = serializers.CharField(source='profile.gender', read_only=True)
    date_joined = serializers.DateTimeField(format="%Y-%m-%d", read_only=True)
    level_of_education = serializers.CharField(
        source='profile.level_of_education',
        allow_blank=True,
        required=False,
        read_only=True)

    language_proficiencies = serializers.SerializerMethodField()
    courses = serializers.SerializerMethodField()

    def get_language_proficiencies(self, user):
        if hasattr(user, 'profiles') and user.profile.language:
            return [user.profile.language]
        else:
            return []

    def get_courses(self, user):
        course_ids = CourseEnrollment.objects.filter(
            user=user).values_list('course_id', flat=True).distinct()

        course_overviews = CourseOverview.objects.filter(
            id__in=[as_course_key(course_id) for course_id in course_ids])

        return [CourseOverviewSerializer(data).data for data in course_overviews]


class UserIndexSerializer(serializers.Serializer):
    """Provides a limited set of user information for summary display
    """
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    fullname = serializers.CharField(
        source='profile.name', default=None, read_only=True)


class UserDemographicSerializer(serializers.Serializer):
    country = SerializeableCountryField(
        source='profile.country', required=False, read_only=True, allow_blank=True)
    year_of_birth = serializers.IntegerField(
        source='profile.year_of_birth', read_only=True)
    gender = serializers.CharField(source='profile.gender', read_only=True)
    level_of_education = serializers.CharField(
        source='profile.level_of_education',
        allow_blank=True,
        required=False,
        read_only=True)


class LearnerCourseDetailsSerializer(serializers.ModelSerializer):
    """
            {
              "course_name": "Something",
              "course_code": "A193",
              "course_id": "A193+2016Q4+something",
              "date_enrolled": "2018-05-06T14:01:58Z",
              "progress_data": {
                "course_completed": "2018-05-06T14:01:58Z", // empty if not completed
                "course_progress": 0.59, // percentage
                "course_progress_history": [
                  {
                    "period": "April 2018",
                    "value": 0.28,
                  },
                  ...
                ]
              }
            }
    """

    course_name = serializers.CharField(source='course_overview.display_name')
    course_code = serializers.CharField(source='course_overview.number')
    course_id = serializers.CharField(source='course_overview.id')
    date_enrolled = serializers.DateTimeField(source='created', format="%Y-%m-%d")
    progress_data = serializers.SerializerMethodField()
    enrollment_id = serializers.IntegerField(source='id')

    class Meta:
        model = CourseEnrollment
        fields = (
            'course_name', 'course_code', 'course_id', 'date_enrolled',
            'progress_data', 'enrollment_id',
            )
        read_only_fields = fields

    def get_progress_data(self, course_enrollment):
        """
        TODO: Add this to metrics, then we'll need to store per-user progress data
        For initial implementation, we get the

        TODO: We will cache course grades, so we'll refactor this method to  use
        the cache, so we'll likely change the call to LearnerCourseGrades
        """
        cert = GeneratedCertificate.objects.filter(
            user=course_enrollment.user,
            course_id=course_enrollment.course_id,
            )

        if cert:
            course_completed = cert[0].created_date
        else:
            course_completed = False

        try:
            obj = LearnerCourseGradeMetrics.objects.most_recent_for_learner_course(
                user=course_enrollment.user,
                course_id=str(course_enrollment.course_id))
            course_progress = dict(
                progress_percent=obj.progress_percent,
                course_progress_details=obj.progress_details)

        except Exception as e:
            error_data = dict(
                msg='Unable to get learner course metrics',
                username=course_enrollment.user.username,
                course_id=str(course_enrollment.course_id),
                exception=str(e)
                )
            log_error(
                error_data=error_data,
                error_type=PipelineError.UNSPECIFIED_DATA,
                )
            course_progress = dict(
                progress_percent=0.0,
                course_progress_details=None)

        # Empty list initially, then will fill after we implement capturing
        # learner specific progress
        course_progress_history = []

        data = dict(
            course_completed=course_completed,
            course_progress=course_progress['progress_percent'],
            course_progress_details=course_progress['course_progress_details'],
            course_progress_history=course_progress_history,
            )
        return data


class LearnerDetailsSerializer(serializers.ModelSerializer):

    """
    {
      "username": "maxi",
      "name": "Maxi Fernandez",
      "country": "UY",
      "is_active": true,
      "year_of_birth": 1985,
      "level_of_education": "b",
      "gender": "m",
      "date_joined": "2018-05-06T14:01:58Z",
      "bio": null,
      "profile_image": {
            "image_url_full": "http://localhost:8000/static/images/profiles/default_500.png",
            "image_url_large": "http://localhost:8000/static/images/profiles/default_120.png",
            "image_url_medium": "http://localhost:8000/static/images/profiles/default_50.png",
            "image_url_small": "http://localhost:8000/static/images/profiles/default_30.png",
            "has_image": false
        },
      "level_of_education": "b",
      "language_proficiencies": [],
      "email": "maxi+localtest@appsembler.com",
      "courses": [
        {
          "course_name": "Something",
          "course_code": "A193",
          "course_id": "A193+2016Q4+something",
          "date_enrolled": "2018-05-06T14:01:58Z",
          "progress_data": {
            "course_completed": "2018-05-06T14:01:58Z", // empty if not completed
            "course_progress": 0.59, // percentage
            "course_progress_history": [
              {
                "period": "April 2018",
                "value": 0.28,
              },
              ...
            ]
          }
        }
        ...
      ]
    }

    """
    name = serializers.CharField(source='profile.name', default=None,)
    country = SerializeableCountryField(
        source='profile.country',
        required=False, allow_blank=True)
    year_of_birth = serializers.IntegerField(source='profile.year_of_birth',)
    gender = serializers.CharField(source='profile.gender',)
    level_of_education = serializers.CharField(
        source='profile.level_of_education',
        allow_blank=True, required=False,)
    bio = serializers.CharField(source='profile.bio', required=False)

    # We may want to exclude this unless we want to show
    # profile images in Figures
    profile_image = serializers.SerializerMethodField()

    language_proficiencies = serializers.SerializerMethodField()

    # Would like to make this work without using the SerializerMethodField
    # courses = LearnerCourseDetailsSerializezr(many=True)
    courses = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        editable = False
        fields = (
            'id', 'username', 'name', 'email', 'country', 'is_active',
            'year_of_birth', 'level_of_education', 'gender', 'date_joined',
            'bio', 'courses', 'language_proficiencies', 'profile_image',
            )
        read_only_fields = fields

    def get_language_proficiencies(self, user):
        if hasattr(user, 'profiles') and user.profile.language:
            return [user.profile.language]
        else:
            return []

    def get_courses(self, user):
        """
        This method is a hack until I figure out customizing DRF fields and/or
        related serializers to explicitly link models not linked via FK
        """
        return LearnerCourseDetailsSerializer(
            CourseEnrollment.objects.filter(user=user), many=True).data

    def get_profile_image(self, user):
        if hasattr(user, 'profile'):
            return AccountLegacyProfileSerializer.get_profile_image(
                            user.profile, user, None)
        else:
            return None
