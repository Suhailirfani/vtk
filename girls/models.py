from django.db import models

# Create your models here.
from datetime import timezone
from django.db import models
from django.contrib.auth.models import AbstractUser
from core.models import User, AbstractUser

# ----------------- Team -----------------
class GirlsTeam(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    total_points = models.IntegerField(default=0)
    # Add fields: college, district etc.
    def __str__(self): return self.name

# ----------------- Category -----------------
class CategoryOff(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self): return self.name

# ----------------- Program -----------------
class ProgramOff(models.Model):
    name = models.CharField(max_length=100)
    category = models.ForeignKey(CategoryOff, on_delete=models.CASCADE)
    is_group = models.BooleanField(default=False, null=True)

    def __str__(self): return f"{self.name} - {self.category.name}"

# ----------------- Contestant -----------------
class ContestantOff(models.Model):
    chest_no = models.PositiveIntegerField(unique=True, null=True)
    name = models.CharField(max_length=100)
    team = models.ForeignKey(GirlsTeam, on_delete=models.CASCADE, null=True, blank=True)
    category = models.ForeignKey(CategoryOff, on_delete=models.CASCADE, null=True)
    total_points = models.IntegerField(default=0)
    

    def __str__(self): return self.name

    def save(self, *args, **kwargs):
        if not self.chest_no:
            last = ContestantOff.objects.all().order_by('-chest_no').first()
            self.chest_no = 1020 if not last else last.chest_no + 1
        super().save(*args, **kwargs)
        
# ----------------- Participation -----------------
class Participation(models.Model):
    contestant = models.ForeignKey(ContestantOff, on_delete=models.CASCADE)
    program = models.ForeignKey(ProgramOff, on_delete=models.CASCADE)
    marks = models.IntegerField(null=True, blank=True)
    rank = models.PositiveIntegerField(null=True, blank=True)
    grade = models.CharField(max_length=1, null=True, blank=True)
    points_awarded = models.BooleanField(default=False)
   
    def __str__(self):
        return f"{self.contestant.name} ({self.program.name})"    



# ----------------- Team Points -----------------
class TeamPointsOff(models.Model):
    team = models.ForeignKey(GirlsTeam, on_delete=models.CASCADE)
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
