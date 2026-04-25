//go:build no_memcache

package reservation

import (
	"context"
	"errors"
	"testing"
	"time"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/reservation/proto"
	"go.mongodb.org/mongo-driver/mongo"
	"pgregory.net/rapid"
)

func TestNoMemcacheReservationProperty(t *testing.T) {
	oldGetCapacityFromMongo := getCapacityFromMongo
	oldCountReservationsFromMongo := countReservationsFromMongo
	oldInsertReservationToMongo := insertReservationToMongo
	t.Cleanup(func() {
		getCapacityFromMongo = oldGetCapacityFromMongo
		countReservationsFromMongo = oldCountReservationsFromMongo
		insertReservationToMongo = oldInsertReservationToMongo
	})

	var capacityCalls []string
	var countCalls []reservation
	var inserts []reservation
	getCapacityFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (int, bool, error) {
		capacityCalls = append(capacityCalls, hotelId)
		return 10, true, nil
	}
	countReservationsFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string, indate string, outdate string) (int, error) {
		countCalls = append(countCalls, reservation{HotelId: hotelId, InDate: indate, OutDate: outdate})
		return 0, nil
	}
	insertReservationToMongo = func(ctx context.Context, client *mongo.Client, r reservation) error {
		inserts = append(inserts, r)
		return nil
	}

	rapid.Check(t, func(t *rapid.T) {
		hotelId := rapid.StringMatching(`[a-z0-9]{1,8}`).Draw(t, "hotelId")
		startOffset := rapid.IntRange(0, 20).Draw(t, "startOffset")
		nights := rapid.IntRange(1, 5).Draw(t, "nights")
		roomNumber := rapid.IntRange(1, 3).Draw(t, "roomNumber")

		base := time.Date(2015, 4, 1, 0, 0, 0, 0, time.UTC)
		inDate := base.AddDate(0, 0, startOffset).Format("2006-01-02")
		outDate := base.AddDate(0, 0, startOffset+nights).Format("2006-01-02")
		req := &pb.Request{
			HotelId:    []string{hotelId},
			InDate:     inDate,
			OutDate:    outDate,
			RoomNumber: int32(roomNumber),
		}

		capacityCalls = capacityCalls[:0]
		countCalls = countCalls[:0]
		inserts = inserts[:0]

		srv := &Server{}
		availability, err := srv.CheckAvailability(context.Background(), req)
		if err != nil {
			t.Fatalf("CheckAvailability returned error: %v", err)
		}
		if len(availability.HotelId) != 1 || availability.HotelId[0] != hotelId {
			t.Fatalf("availability.HotelId = %v, want [%s]", availability.HotelId, hotelId)
		}
		if len(capacityCalls) != 1 || capacityCalls[0] != hotelId {
			t.Fatalf("capacity calls = %v, want [%s]", capacityCalls, hotelId)
		}
		if len(countCalls) != nights {
			t.Fatalf("count calls = %d, want %d", len(countCalls), nights)
		}

		reservationResult, err := srv.MakeReservation(context.Background(), req)
		if err != nil {
			t.Fatalf("MakeReservation returned error: %v", err)
		}
		if len(reservationResult.HotelId) != 1 || reservationResult.HotelId[0] != hotelId {
			t.Fatalf("reservationResult.HotelId = %v, want [%s]", reservationResult.HotelId, hotelId)
		}
		if len(inserts) != nights {
			t.Fatalf("inserts = %d, want %d", len(inserts), nights)
		}
	})
}

func TestNoMemcacheReservationReturnsMongoError(t *testing.T) {
	oldGetCapacityFromMongo := getCapacityFromMongo
	t.Cleanup(func() {
		getCapacityFromMongo = oldGetCapacityFromMongo
	})

	wantErr := errors.New("mongo failed")
	getCapacityFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (int, bool, error) {
		return 0, false, wantErr
	}

	_, err := (&Server{}).CheckAvailability(context.Background(), &pb.Request{
		HotelId:    []string{"1"},
		InDate:     "2015-04-01",
		OutDate:    "2015-04-02",
		RoomNumber: 1,
	})
	if !errors.Is(err, wantErr) {
		t.Fatalf("CheckAvailability error = %v, want %v", err, wantErr)
	}
}
