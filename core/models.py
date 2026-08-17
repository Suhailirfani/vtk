from datetime import timezone
from django.utils import timezone
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser

# ----------------- Custom User -----------------
class User(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('team', 'Team'),
        ('off_campus', 'Off_campus')
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    is_approved = models.BooleanField(default=False)

# ----------------- Admin Profile -----------------
class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    designation = models.CharField(max_length=100, default='Coordinator')


# -------------------campus - offcampus separation ----------------
class Competition(models.Model):
    COMPETITION_TYPES = [
        ("ON", "On-Campus"),
        ("OFF", "Off-Campus"),
    ]
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=3, choices=COMPETITION_TYPES)
    year = models.PositiveIntegerField(default=2025)  # optional, if yearly fest
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


# ----------------- Team -----------------
class Team(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, null=True, blank=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    total_points = models.IntegerField(default=0)
    # Add fields: college, district etc.
    def __str__(self): return self.name

# ----------------- Category -----------------
class Category(models.Model):
    COMPETITION_TYPES = [
        ('MAIN', 'Main Campus'),
        ('OFF', 'Off Campus'),
    ]
    name = models.CharField(max_length=100)
    competition_type = models.CharField(max_length=10, choices=COMPETITION_TYPES, default='MAIN')
    is_common = models.BooleanField(
        default=False, 
        help_text="True if this is a combined/common category containing multiple base categories"
    )
    included_categories = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='parent_common_categories',
        help_text="Included base categories for this common category"
    )

    def __str__(self):
        if self.is_common:
            inc_list = ", ".join([c.name for c in self.included_categories.all()])
            return f"{self.name} [Common: {inc_list or 'All'}]"
        return f"{self.name} ({self.get_competition_type_display()})"

    def get_eligible_categories(self):
        """Returns list of Category objects eligible for this category (included base categories for combined categories)."""
        if self.is_common:
            if self.included_categories.exists():
                return list(self.included_categories.all())
            return list(Category.objects.filter(is_common=False))
        return [self]



# ----------------- Program -----------------
class Program(models.Model):
    PROGRAM_TYPES = (
        ('STAGE', 'Stage Program'),
        ('OFF_STAGE', 'Off-Stage Program'),
    )
    PRESENTATION_MODES = (
        ('SEQUENTIAL', 'Per Participant (Sequential)'),
        ('SIMULTANEOUS', 'All-at-Once (Simultaneous/Written)'),
    )
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    is_group = models.BooleanField(default=False, null=True)
    members_count = models.PositiveIntegerField(null=True, blank=True, default=1)
    program_type = models.CharField(max_length=15, choices=PROGRAM_TYPES, default='STAGE')
    presentation_mode = models.CharField(max_length=15, choices=PRESENTATION_MODES, default='SEQUENTIAL', help_text="Sequential (Speech/Song) vs Simultaneous (Essay/Drawing)")
    duration_per_participant = models.PositiveIntegerField(default=5, help_text="Duration in minutes per participant (or total fixed mins if simultaneous)")
    buffer_margin_minutes = models.PositiveIntegerField(default=0, help_text="Extra buffer time in minutes")
    preferred_stage = models.ForeignKey('Stage', on_delete=models.SET_NULL, null=True, blank=True, related_name='preferred_programs', help_text="Priority stage venue for popular events")
    is_announced = models.BooleanField(default=False, help_text="Make results public")
    announced_at = models.DateTimeField(null=True, blank=True)
    result_number = models.PositiveIntegerField(null=True, blank=True)  # 🆕 new field

    def __str__(self): return f"{self.name} - {self.category.name}"

# ----------------- Contestant -----------------
class Contestant(models.Model):
    chest_no = models.PositiveIntegerField(unique=True, null=True)
    name = models.CharField(max_length=100)
    student_class = models.CharField(max_length=50, blank=True, null=True, verbose_name="Class")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True)
    total_points = models.IntegerField(default=0)
    

    def __str__(self):
        if self.student_class:
            return f"{self.name} - {self.student_class}"
        return self.name

    @property
    def display_name(self):
        if self.student_class:
            return f"{self.name} - {self.student_class}"
        return self.name

    def save(self, *args, **kwargs):
        if not self.chest_no:
            last = Contestant.objects.all().order_by('-chest_no').first()
            self.chest_no = 1020 if not last else last.chest_no + 1
        super().save(*args, **kwargs)
        
# ----------------- Participation -----------------
class Participation(models.Model):
    contestant = models.ForeignKey(Contestant, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    marks = models.IntegerField(null=True, blank=True)
    code_letter = models.CharField(max_length=2, null=True, blank=True)
    rank = models.PositiveIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=1, null=True, blank=True)
    points_awarded = models.BooleanField(default=False)
    marks_added_at = models.DateTimeField(default=timezone.now, null=True, blank=True)
   
    def __str__(self):
        return f"{self.contestant.name} ({self.program.name})"    

# ----------------- Group Participation -----------------
class GroupParticipation(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    contestants = models.ManyToManyField(Contestant)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)  # All contestants should be from same team
    group_name = models.CharField(max_length=200, blank=True)  # Optional group name
    captain = models.ForeignKey(Contestant, on_delete=models.SET_NULL, null=True, blank=True, related_name='captain_groups')
    code_letter = models.CharField(max_length=5, null=True, blank=True)
    marks = models.IntegerField(null=True, blank=True)
    rank = models.PositiveIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=1, null=True, blank=True)
    points_awarded = models.BooleanField(default=False)

    def __str__(self):
        contestant_names = ", ".join([c.name for c in self.contestants.all()])
        return f"{contestant_names} ({self.program.name})"

    @property
    def captain_display(self):
        if self.captain:
            return f"#{self.captain.chest_no} {self.captain.name}"
        first = self.contestants.first()
        if first:
            return f"#{first.chest_no} {first.name}"
        return self.group_name or (self.team.name if self.team else "Group")

    @property
    def members_display(self):
        members = list(self.contestants.all())
        if not members:
            return "No members assigned"
        cap_id = self.captain_id or (members[0].id if members else None)
        out = []
        for m in members:
            is_cap = (m.id == cap_id)
            tag = " (Captain)" if is_cap else ""
            out.append(f"#{m.chest_no} {m.name}{tag}")
        return ", ".join(out)

    def get_contestant_names(self):
        return ", ".join([contestant.name for contestant in self.contestants.all()])

    def save(self, *args, **kwargs):
        # Validate that the program is a group program
        if not self.program.is_group:
            raise ValueError("Cannot create group participation for non-group program")
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Check if program is group program
        if not self.program.is_group:
            raise ValidationError("This program is not a group program")
        
        # Check participant count (this will be validated in views/forms)
        if hasattr(self, 'contestants') and self.pk:
            count = self.contestants.count()
            max_members = self.program.members_count or 1
            if count < 1 or count > max_members:
                raise ValidationError(
                    f"Number of participants must be between 1 and {max_members}"
                )

# ----------------- Team Points -----------------
class TeamPoints(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)

# ----------------- Points Configuration -----------------
class PointsConfig(models.Model):
    """Configuration for points calculation"""
    # Rank-based points
    rank_1_points = models.IntegerField(default=10)
    rank_2_points = models.IntegerField(default=6)
    rank_3_points = models.IntegerField(default=3)
    
    # Grade-based points
    grade_a_points = models.IntegerField(default=10)
    grade_b_points = models.IntegerField(default=6)
    grade_c_points = models.IntegerField(default=3)
    
    # Grade thresholds
    grade_a_threshold = models.IntegerField(default=80)
    grade_b_threshold = models.IntegerField(default=70)
    grade_c_threshold = models.IntegerField(default=60)
    
    class Meta:
        # Ensure only one configuration exists
        verbose_name = "Points Configuration"
        verbose_name_plural = "Points Configuration"

    @classmethod
    def get_config(cls):
        """Get or create the points configuration"""
        config, created = cls.objects.get_or_create(id=1)
        return config

# ----------------- System Setting -----------------
class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_setting(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default


# ----------------- Fest Days & Schedule -----------------
class FestDay(models.Model):
    day_number = models.PositiveIntegerField(unique=True)
    date = models.DateField(null=True, blank=True)
    name = models.CharField(max_length=100, blank=True)
    start_time = models.TimeField(default='09:00', help_text="Operating start time for this day")
    end_time = models.TimeField(default='21:00', help_text="Operating end time for this day")

    class Meta:
        ordering = ['day_number']

    def __str__(self):
        time_str = f"[{self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')}]"
        if self.name:
            return f"Day {self.day_number} ({self.name}) {time_str}"
        if self.date:
            return f"Day {self.day_number} - {self.date.strftime('%d %b %Y')} {time_str}"
        return f"Day {self.day_number} {time_str}"


class Stage(models.Model):
    STAGE_TYPES = (
        ('STAGE', 'Stage Venue'),
        ('OFF_STAGE', 'Off-Stage Venue'),
    )
    name = models.CharField(max_length=100)
    stage_type = models.CharField(max_length=15, choices=STAGE_TYPES, default='STAGE')
    location_details = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['stage_type', 'name']

    def __str__(self):
        return f"{self.name} [{self.get_stage_type_display()}]"


class ProgramSchedule(models.Model):
    program = models.OneToOneField(Program, on_delete=models.CASCADE, related_name='schedule')
    fest_day = models.ForeignKey(FestDay, on_delete=models.CASCADE, related_name='schedules')
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name='schedules')
    order = models.PositiveIntegerField(default=1, help_text="Order/sequence of the program on this stage for the day")
    start_time = models.TimeField()
    end_time = models.TimeField()
    total_duration_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['fest_day__day_number', 'stage', 'order', 'start_time']

    def __str__(self):
        return f"{self.program.name} ({self.fest_day} @ {self.stage.name}: {self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')})"

